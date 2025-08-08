<script lang="ts">
	import Fuse from 'fuse.js';
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { onMount, getContext, onDestroy, tick } from 'svelte';
	const i18n = getContext('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		mobile,
		showSidebar,
		knowledge as _knowledge,
		config,
		user,
		settings
	} from '$lib/stores';
	import { progressStore } from '$lib/stores/progress';

	import {
		updateFileDataContentById,
		uploadFile,
		deleteFileById,
		getFileById,
		getFileDataContentById,
		transcribeFileById
	} from '$lib/apis/files';
	import {
		addFileToKnowledgeById,
		getKnowledgeById,
		getKnowledgeBases,
		removeFileFromKnowledgeById,
		resetKnowledgeById,
		updateFileFromKnowledgeById,
		updateKnowledgeById,
		addGoogleDriveFileToKnowledge,
		addGoogleDriveFolderToKnowledge
	} from '$lib/apis/knowledge';
	import { blobToFile } from '$lib/utils';
	import { createPicker, getAuthToken } from '$lib/utils/google-drive-picker';
	import { checkAndResumeDatabaseSessions } from '$lib/utils/polling';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Files from './KnowledgeBase/Files.svelte';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';

	import AddContentMenu from './KnowledgeBase/AddContentMenu.svelte';
	import AddTextContentModal from './KnowledgeBase/AddTextContentModal.svelte';

	import SyncConfirmDialog from '../../common/ConfirmDialog.svelte';
	import RichTextInput from '$lib/components/common/RichTextInput.svelte';
	import EllipsisVertical from '$lib/components/icons/EllipsisVertical.svelte';
	import Drawer from '$lib/components/common/Drawer.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import Search from '$lib/components/icons/Search.svelte';

	let largeScreen = true;

	let pane;
	let showSidepanel = true;
	let minSize = 0;

	type Knowledge = {
		id: string;
		name: string;
		description: string;
		data: {
			file_ids: string[];
		};
		files: any[];
	};

	let id = null;
	let knowledge: Knowledge | null = null;
	let query = '';

	let showAddTextContentModal = false;
	let showSyncConfirmModal = false;
	let showAccessControlModal = false;

	let inputFiles = null;

	let filteredItems = [];
	$: if (knowledge && knowledge.files) {
		fuse = new Fuse(knowledge.files, {
			keys: ['meta.name', 'meta.description']
		});
	}

	$: if (fuse) {
		filteredItems = query
			? fuse.search(query).map((e) => {
					return e.item;
				})
			: (knowledge?.files ?? []);
	}

	let selectedFile = null;
	let selectedFileId = null;
	let selectedFileContent = '';

	// Add cache object
	let fileContentCache = new Map();

	$: if (selectedFileId) {
		const file = (knowledge?.files ?? []).find((file) => file.id === selectedFileId);
		if (file) {
			fileSelectHandler(file);
		} else {
			selectedFile = null;
		}
	} else {
		selectedFile = null;
	}

	let fuse = null;
	let debounceTimeout = null;
	let mediaQuery;
	let dragged = false;

	const createFileFromText = (name, content) => {
		const blob = new Blob([content], { type: 'text/plain' });
		const file = blobToFile(blob, `${name}.txt`);

		console.log(file);
		return file;
	};

	const uploadFileHandler = async (file) => {
		console.log(file);

		const tempItemId = uuidv4();
		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: '',
			name: file.name,
			size: file.size,
			status: 'uploading',
			error: '',
			itemId: tempItemId
		};

		if (fileItem.size == 0) {
			toast.error($i18n.t('You cannot upload an empty file.'));
			return null;
		}

		if (
			($config?.file?.max_size ?? null) !== null &&
			file.size > ($config?.file?.max_size ?? 0) * 1024 * 1024
		) {
			console.log('File exceeds max size limit:', {
				fileSize: file.size,
				maxSize: ($config?.file?.max_size ?? 0) * 1024 * 1024
			});
			toast.error(
				$i18n.t(`File size should not exceed {{maxSize}} MB.`, {
					maxSize: $config?.file?.max_size
				})
			);
			return;
		}

		knowledge.files = [...(knowledge.files ?? []), fileItem];

		try {
			// If the file is an audio file, provide the language for STT.
			let metadata = null;
			if (
				(file.type.startsWith('audio/') || file.type.startsWith('video/')) &&
				$settings?.audio?.stt?.language
			) {
				metadata = {
					language: $settings?.audio?.stt?.language
				};
			}

			const uploadedFile = await uploadFile(localStorage.token, file, metadata).catch((e) => {
				toast.error(`${e}`);
				return null;
			});

			if (uploadedFile) {
				console.log(uploadedFile);
				knowledge.files = knowledge.files.map((item) => {
					if (item.itemId === tempItemId) {
						item.id = uploadedFile.id;
					}

					// Remove temporary item id
					delete item.itemId;
					return item;
				});
				await addFileHandler(uploadedFile.id);
			} else {
				toast.error($i18n.t('Failed to upload file.'));
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	// Google Drive integration handlers
	const uploadGoogleDriveFileHandler = async () => {
		console.log('=== uploadGoogleDriveFileHandler called ===');
		try {
			const fileData = await createPicker();
			console.log('File data from picker:', fileData);
			if (fileData) {
				// Get OAuth token for server-side processing
				const oauthToken = await getAuthToken();
				console.log('OAuth token obtained');
				
				// Show initial progress message
				toast.info($i18n.t('Processing Google Drive file...'));
				
				// Add file to knowledge base using server-side API
				console.log('Calling addGoogleDriveFileToKnowledge API');
				const result = await addGoogleDriveFileToKnowledge(
					localStorage.token,
					id,
					fileData.id,
					oauthToken
				);
				console.log('API result:', result);

				if (result && result.session_id) {
					// Create session and start tracking with the real session ID
					console.log('Creating session with real session ID:', result.session_id);
					
					// Import and create session
					import('$lib/stores/progress.js').then(({ progressStore }) => {
						progressStore.startSession(result.session_id, 1, [fileData.name || fileData.id]);
					});
					
					// Start polling tracking
					console.log('Starting polling tracking for real session:', result.session_id);
					import('$lib/utils/polling.js').then(({ startProgressTracking }) => {
						startProgressTracking(result.session_id, () => {
							// Refresh knowledge base data when session completes
							loadKnowledgeData();
						}, (error) => {
							console.error('Polling failed:', error);
							toast.error($i18n.t('Failed to track progress. Progress updates may not be visible.'));
						});
					});
					
					// Refresh knowledge base data
					await loadKnowledgeData();
					// Progress will be shown via SSE events
				}
			} else {
				console.log('No file was selected from Google Drive');
			}
		} catch (error) {
			console.error('Google Drive Error:', error);
			
			// Provide more specific error messages
			let errorMessage = error.message;
			if (error.message.includes('empty content') || error.message.includes('Could not extract content')) {
				errorMessage = 'The file could not be processed. This may be because it\'s empty, corrupted, or in an unsupported format. For video/audio files, ensure transcription is enabled in your settings.';
			} else if (error.message.includes('not supported for processing')) {
				errorMessage = 'This file type is not supported for processing. Please try a different file format.';
			} else if (error.message.includes('Media files (audio/video) are supported')) {
				errorMessage = error.message;
			}
			
			toast.error(
				$i18n.t('Error accessing Google Drive: {{error}}', {
					error: errorMessage
				})
			);
		}
	};

	const uploadGoogleDriveFolderHandler = async () => {
		try {
			console.log('=== uploadGoogleDriveFolderHandler called ===');
			// Use the enhanced picker with folder support
			const folderData = await createPicker(true); // includeFolders = true
			
			console.log('Google Drive folder picker result:', folderData);
			
			if (folderData && folderData.type === 'folder') {
				// Get OAuth token for server-side processing
				const oauthToken = await getAuthToken();
				
				// Show initial progress message
				toast.info($i18n.t('Processing Google Drive folder... This may take a while.'));
				
				// Start progress tracking immediately with the knowledge base ID as session ID
				console.log('Starting progress tracking immediately for session:', id);
				import('$lib/stores/progress.js').then(({ progressStore }) => {
					progressStore.startSession(id, 1, [folderData.name || folderData.id]);
				});
				
				// Start polling immediately
				import('$lib/utils/polling.js').then(({ startProgressTracking }) => {
					startProgressTracking(id, () => {
						// Refresh knowledge base data when session completes
						loadKnowledgeData();
					}, (error) => {
						console.error('Polling failed:', error);
						toast.error($i18n.t('Failed to track progress. Progress updates may not be visible.'));
					});
				});
				
				// Add folder to knowledge base using server-side API
				console.log('Calling addGoogleDriveFolderToKnowledge with:', {
					token: localStorage.token ? 'present' : 'missing',
					knowledgeId: id,
					folderId: folderData.id,
					oauthToken: oauthToken ? 'present' : 'missing',
					recursive: true
				});
				
				const result = await addGoogleDriveFolderToKnowledge(
					localStorage.token,
					id,
					folderData.id,
					oauthToken,
					true // recursive
				);
				
				console.log('addGoogleDriveFolderToKnowledge result:', result);

				if (result) {
					// Refresh knowledge base data
					await loadKnowledgeData();
					
					// Show success message with warnings if any
					if (result.warnings) {
						toast.success(result.warnings.message);
					}
				}
			} else if (folderData && folderData.type === 'file') {
				// User selected a file instead of a folder, handle it as a single file
				const oauthToken = await getAuthToken();
				
				toast.info($i18n.t('Processing Google Drive file...'));
				
				// Make API call and get session ID from response
				const result = await addGoogleDriveFileToKnowledge(
					localStorage.token,
					id,
					folderData.id,
					oauthToken
				);

				if (result && result.session_id) {
					// Create session and start tracking with the real session ID
					console.log('Creating session with real session ID (folder flow):', result.session_id);
					
					// Import and create session
					import('$lib/stores/progress.js').then(({ progressStore }) => {
						progressStore.startSession(result.session_id, 1, [folderData.name || folderData.id]);
					});
					
					// Start polling tracking
					console.log('Starting polling tracking for real session (folder flow):', result.session_id);
					import('$lib/utils/polling.js').then(({ startProgressTracking }) => {
						startProgressTracking(result.session_id, () => {
							// Refresh knowledge base data when session completes
							loadKnowledgeData();
						}, (error) => {
							console.error('Polling failed (folder flow):', error);
							toast.error($i18n.t('Failed to track progress. Progress updates may not be visible.'));
						});
					});
					
					await loadKnowledgeData();
					// Progress will be shown via SSE events
				}
			} else {
				console.log('No folder was selected from Google Drive');
			}
		} catch (error) {
			console.error('Google Drive Folder Error:', error);
			
			// Provide more specific error messages
			let errorMessage = error.message || 'Unknown error occurred';
			if (errorMessage.includes('empty content') || errorMessage.includes('Could not extract content')) {
				errorMessage = 'Some files could not be processed. This may be because they are empty, corrupted, or in an unsupported format. For video/audio files, ensure transcription is enabled in your settings.';
			} else if (errorMessage.includes('not supported for processing')) {
				errorMessage = 'Some file types are not supported for processing. Please try different file formats.';
			} else if (errorMessage.includes('Media files (audio/video) are supported')) {
				errorMessage = errorMessage;
			} else if (errorMessage.includes('name \'uuid\' is not defined')) {
				errorMessage = 'Server configuration error. Please try again or contact support.';
			}
			
			toast.error(
				$i18n.t('Error accessing Google Drive folder: {{error}}', {
					error: errorMessage
				})
			);
		}
	};

	const uploadDirectoryHandler = async () => {
		// Check if File System Access API is supported
		const isFileSystemAccessSupported = 'showDirectoryPicker' in window;

		try {
			if (isFileSystemAccessSupported) {
				// Modern browsers (Chrome, Edge) implementation
				await handleModernBrowserUpload();
			} else {
				// Firefox fallback
				await handleFirefoxUpload();
			}
		} catch (error) {
			handleUploadError(error);
		}
	};

	// Helper function to check if a path contains hidden folders
	const hasHiddenFolder = (path) => {
		return path.split('/').some((part) => part.startsWith('.'));
	};

	// Modern browsers implementation using File System Access API
	const handleModernBrowserUpload = async () => {
		const dirHandle = await window.showDirectoryPicker();
		let totalFiles = 0;
		let uploadedFiles = 0;

		// Function to update the UI with the progress
		const updateProgress = () => {
			const percentage = (uploadedFiles / totalFiles) * 100;
			toast.info(`Upload Progress: ${uploadedFiles}/${totalFiles} (${percentage.toFixed(2)}%)`);
		};

		// Recursive function to count all files excluding hidden ones
		async function countFiles(dirHandle) {
			for await (const entry of dirHandle.values()) {
				// Skip hidden files and directories
				if (entry.name.startsWith('.')) continue;

				if (entry.kind === 'file') {
					totalFiles++;
				} else if (entry.kind === 'directory') {
					// Only process non-hidden directories
					if (!entry.name.startsWith('.')) {
						await countFiles(entry);
					}
				}
			}
		}

		// Recursive function to process directories excluding hidden files and folders
		async function processDirectory(dirHandle, path = '') {
			for await (const entry of dirHandle.values()) {
				// Skip hidden files and directories
				if (entry.name.startsWith('.')) continue;

				const entryPath = path ? `${path}/${entry.name}` : entry.name;

				// Skip if the path contains any hidden folders
				if (hasHiddenFolder(entryPath)) continue;

				if (entry.kind === 'file') {
					const file = await entry.getFile();
					const fileWithPath = new File([file], entryPath, { type: file.type });

					await uploadFileHandler(fileWithPath);
					uploadedFiles++;
					updateProgress();
				} else if (entry.kind === 'directory') {
					// Only process non-hidden directories
					if (!entry.name.startsWith('.')) {
						await processDirectory(entry, entryPath);
					}
				}
			}
		}

		await countFiles(dirHandle);
		updateProgress();

		if (totalFiles > 0) {
			await processDirectory(dirHandle);
		} else {
			console.log('No files to upload.');
		}
	};

	// Firefox fallback implementation using traditional file input
	const handleFirefoxUpload = async () => {
		return new Promise((resolve, reject) => {
			// Create hidden file input
			const input = document.createElement('input');
			input.type = 'file';
			input.webkitdirectory = true;
			input.directory = true;
			input.multiple = true;
			input.style.display = 'none';

			// Add input to DOM temporarily
			document.body.appendChild(input);

			input.onchange = async () => {
				try {
					const files = Array.from(input.files)
						// Filter out files from hidden folders
						.filter((file) => !hasHiddenFolder(file.webkitRelativePath));

					let totalFiles = files.length;
					let uploadedFiles = 0;

					// Function to update the UI with the progress
					const updateProgress = () => {
						const percentage = (uploadedFiles / totalFiles) * 100;
						toast.info(
							`Upload Progress: ${uploadedFiles}/${totalFiles} (${percentage.toFixed(2)}%)`
						);
					};

					updateProgress();

					// Process all files
					for (const file of files) {
						// Skip hidden files (additional check)
						if (!file.name.startsWith('.')) {
							const relativePath = file.webkitRelativePath || file.name;
							const fileWithPath = new File([file], relativePath, { type: file.type });

							await uploadFileHandler(fileWithPath);
							uploadedFiles++;
							updateProgress();
						}
					}

					// Clean up
					document.body.removeChild(input);
					resolve();
				} catch (error) {
					reject(error);
				}
			};

			input.onerror = (error) => {
				document.body.removeChild(input);
				reject(error);
			};

			// Trigger file picker
			input.click();
		});
	};

	// Error handler
	const handleUploadError = (error) => {
		if (error.name === 'AbortError') {
			toast.info('Directory selection was cancelled');
		} else {
			toast.error('Error accessing directory');
			console.error('Directory access error:', error);
		}
	};

	// Helper function to maintain file paths within zip
	const syncDirectoryHandler = async () => {
		if ((knowledge?.files ?? []).length > 0) {
			const res = await resetKnowledgeById(localStorage.token, id).catch((e) => {
				toast.error(`${e}`);
			});

			if (res) {
				knowledge = res;
				toast.success($i18n.t('Knowledge reset successfully.'));

				// Upload directory
				uploadDirectoryHandler();
			}
		} else {
			uploadDirectoryHandler();
		}
	};

	const addFileHandler = async (fileId) => {
		const updatedKnowledge = await addFileToKnowledgeById(localStorage.token, id, fileId).catch(
			(e) => {
				toast.error(`${e}`);
				return null;
			}
		);

		if (updatedKnowledge) {
			knowledge = updatedKnowledge;
			toast.success($i18n.t('File added successfully.'));
		} else {
			toast.error($i18n.t('Failed to add file.'));
			knowledge.files = knowledge.files.filter((file) => file.id !== fileId);
		}
	};

	const deleteFileHandler = async (fileId) => {
		try {
			console.log('Starting file deletion process for:', fileId);

			// Remove from knowledge base only
			const updatedKnowledge = await removeFileFromKnowledgeById(localStorage.token, id, fileId);

			console.log('Knowledge base updated:', updatedKnowledge);

			if (updatedKnowledge) {
				knowledge = updatedKnowledge;
				toast.success($i18n.t('File removed successfully.'));
			}
		} catch (e) {
			console.error('Error in deleteFileHandler:', e);
			toast.error(`${e}`);
		}
	};

	const updateFileContentHandler = async () => {
		const fileId = selectedFile.id;
		const content = selectedFileContent;

		// Clear the cache for this file since we're updating it
		fileContentCache.delete(fileId);

		const res = updateFileDataContentById(localStorage.token, fileId, content).catch((e) => {
			toast.error(`${e}`);
		});

		const updatedKnowledge = await updateFileFromKnowledgeById(
			localStorage.token,
			id,
			fileId
		).catch((e) => {
			toast.error(`${e}`);
		});

		if (res && updatedKnowledge) {
			knowledge = updatedKnowledge;
			toast.success($i18n.t('File content updated successfully.'));
		}
	};

	const changeDebounceHandler = () => {
		console.log('debounce');
		if (debounceTimeout) {
			clearTimeout(debounceTimeout);
		}

		debounceTimeout = setTimeout(async () => {
			if (knowledge.name.trim() === '' || knowledge.description.trim() === '') {
				toast.error($i18n.t('Please fill in all fields.'));
				return;
			}

			const res = await updateKnowledgeById(localStorage.token, id, {
				...knowledge,
				name: knowledge.name,
				description: knowledge.description,
				access_control: knowledge.access_control
			}).catch((e) => {
				toast.error(`${e}`);
			});

			if (res) {
				toast.success($i18n.t('Knowledge updated successfully'));
				_knowledge.set(await getKnowledgeBases(localStorage.token));
			}
		}, 1000);
	};

	const handleMediaQuery = async (e) => {
		if (e.matches) {
			largeScreen = true;
		} else {
			largeScreen = false;
		}
	};

	const transcribeFileHandler = async (file) => {
		try {
			toast.info($i18n.t('Transcribing file... This may take a few minutes.'));
			
			const response = await transcribeFileById(localStorage.token, file.id);
			
			if (response && response.content !== undefined) {
				selectedFileContent = response.content;
				// Cache the content
				fileContentCache.set(file.id, response.content);
				toast.success($i18n.t('File transcribed successfully!'));
			} else {
				toast.error($i18n.t('Failed to transcribe file.'));
			}
		} catch (e) {
			toast.error($i18n.t('Failed to transcribe file: ') + e);
		}
	};

	const fileSelectHandler = async (file) => {
		try {
			selectedFile = file;

			// Check cache first
			if (fileContentCache.has(file.id)) {
				selectedFileContent = fileContentCache.get(file.id);
				return;
			}

			const response = await getFileDataContentById(localStorage.token, file.id);
			
			if (response && response.content !== undefined && response.content.trim() !== '') {
				selectedFileContent = response.content;
				// Cache the content
				fileContentCache.set(file.id, response.content);
			} else {
				// If no content found, show appropriate message
				selectedFileContent = '';
				if (file.meta?.content_type?.startsWith('video/') || file.meta?.content_type?.startsWith('audio/')) {
					// Don't show error for video/audio files, just set empty content
					// The UI will show a transcription button
				} else {
					toast.error($i18n.t('No content found in file.'));
				}
			}
		} catch (e) {
			selectedFileContent = '';
			toast.error($i18n.t('Failed to load file content.'));
		}
	};

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being draggedOver.
		if (e.dataTransfer?.types?.includes('Files')) {
			dragged = true;
		} else {
			dragged = false;
		}
	};

	const onDragLeave = () => {
		dragged = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();
		dragged = false;

		if (e.dataTransfer?.types?.includes('Files')) {
			if (e.dataTransfer?.files) {
				const inputFiles = e.dataTransfer?.files;

				if (inputFiles && inputFiles.length > 0) {
					for (const file of inputFiles) {
						await uploadFileHandler(file);
					}
				} else {
					toast.error($i18n.t(`File not found.`));
				}
			}
		}
	};

	const loadKnowledgeData = async () => {
		if (!id) return;
		
		const res = await getKnowledgeById(localStorage.token, id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			knowledge = res;
		}
	};

	onMount(async () => {
		// listen to resize 1024px
		mediaQuery = window.matchMedia('(min-width: 1024px)');

		mediaQuery.addEventListener('change', handleMediaQuery);
		handleMediaQuery(mediaQuery);

		// Select the container element you want to observe
		const container = document.getElementById('collection-container');

		// initialize the minSize based on the container width
		minSize = !largeScreen ? 100 : Math.floor((300 / container.clientWidth) * 100);

		// Create a new ResizeObserver instance
		const resizeObserver = new ResizeObserver((entries) => {
			for (let entry of entries) {
				const width = entry.contentRect.width;
				// calculate the percentage of 300
				const percentage = (300 / width) * 100;
				// set the minSize to the percentage, must be an integer
				minSize = !largeScreen ? 100 : Math.floor(percentage);

				if (showSidepanel) {
					if (pane && pane.isExpanded() && pane.getSize() < minSize) {
						pane.resize(minSize);
					}
				}
			}
		});

		// Start observing the container's size changes
		resizeObserver.observe(container);

		if (pane) {
			pane.expand();
		}

		id = $page.params.id;

		const res = await getKnowledgeById(localStorage.token, id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			knowledge = res;
			
			// Check for active sessions in the current knowledge base
			if (knowledge.meta && knowledge.meta.processing_progress) {
				console.log('KnowledgeBase: Found processing_progress in current knowledge base:', knowledge.meta.processing_progress);
				
				const progress = knowledge.meta.processing_progress;
				const isActive = progress.status === 'processing' || progress.status === 'transcribing';
				const isStale = (Date.now() - progress.last_updated * 1000) > 5 * 60 * 1000; // 5 minutes
				
				console.log('KnowledgeBase: Session status - active:', isActive, 'stale:', isStale, 'status:', progress.status);
				
				if (isActive && !isStale) {
					console.log('KnowledgeBase: Resuming active session for current knowledge base:', knowledge.id);
					
                    // Create session in progress store (prefer full list when available)
                    const fileList = (Array.isArray(progress.file_list) && progress.file_list.length > 0)
                        ? progress.file_list
                        : (progress.current_file ? [progress.current_file] : ['Processing...']);
					progressStore.startSession(knowledge.id, progress.total_files || 1, fileList);
					
					// Resume polling
					import('$lib/utils/polling.js').then(({ startProgressTracking }) => {
						startProgressTracking(knowledge.id, () => {
							console.log('KnowledgeBase: Session completed:', knowledge.id);
							loadKnowledgeData(); // Refresh data when complete
						}, (error) => {
							console.error('KnowledgeBase: Session error:', error);
						});
					});
				}
			} else {
				console.log('KnowledgeBase: No processing_progress found in current knowledge base');
			}
		} else {
			goto('/workspace/knowledge');
		}

		// Also check for active sessions in other knowledge bases
		await checkAndResumeDatabaseSessions();

		const dropZone = document.querySelector('body');
		dropZone?.addEventListener('dragover', onDragOver);
		dropZone?.addEventListener('drop', onDrop);
		dropZone?.addEventListener('dragleave', onDragLeave);
	});

	onDestroy(() => {
		mediaQuery?.removeEventListener('change', handleMediaQuery);
		const dropZone = document.querySelector('body');
		dropZone?.removeEventListener('dragover', onDragOver);
		dropZone?.removeEventListener('drop', onDrop);
		dropZone?.removeEventListener('dragleave', onDragLeave);
	});

	const decodeString = (str: string) => {
		try {
			return decodeURIComponent(str);
		} catch (e) {
			return str;
		}
	};
</script>

{#if dragged}
	<div
		class="fixed {$showSidebar
			? 'left-0 md:left-[260px] md:w-[calc(100%-260px)]'
			: 'left-0'}  w-full h-full flex z-50 touch-none pointer-events-none"
		id="dropzone"
		role="region"
		aria-label="Drag and Drop Container"
	>
		<div class="absolute w-full h-full backdrop-blur-sm bg-gray-800/40 flex justify-center">
			<div class="m-auto pt-64 flex flex-col justify-center">
				<div class="max-w-md">
					<AddFilesPlaceholder>
						<div class=" mt-2 text-center text-sm dark:text-gray-200 w-full">
							Drop any files here to add to my documents
						</div>
					</AddFilesPlaceholder>
				</div>
			</div>
		</div>
	</div>
{/if}

<SyncConfirmDialog
	bind:show={showSyncConfirmModal}
	message={$i18n.t(
		'This will reset the knowledge base and sync all files. Do you wish to continue?'
	)}
	on:confirm={() => {
		syncDirectoryHandler();
	}}
/>

<AddTextContentModal
	bind:show={showAddTextContentModal}
	on:submit={(e) => {
		const file = createFileFromText(e.detail.name, e.detail.content);
		uploadFileHandler(file);
	}}
/>

<input
	id="files-input"
	bind:files={inputFiles}
	type="file"
	multiple
	hidden
	on:change={async () => {
		if (inputFiles && inputFiles.length > 0) {
			for (const file of inputFiles) {
				await uploadFileHandler(file);
			}

			inputFiles = null;
			const fileInputElement = document.getElementById('files-input');

			if (fileInputElement) {
				fileInputElement.value = '';
			}
		} else {
			toast.error($i18n.t(`File not found.`));
		}
	}}
/>

<div class="flex flex-col w-full translate-y-1" id="collection-container">
	{#if id && knowledge}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={knowledge.access_control}
			allowPublic={$user?.permissions?.sharing?.public_knowledge || $user?.role === 'admin'}
			onChange={() => {
				changeDebounceHandler();
			}}
			accessRoles={['read', 'write']}
		/>
		<div class="w-full mb-2.5">
			<div class=" flex w-full">
				<div class="flex-1">
					<div class="flex items-center justify-between w-full px-0.5 mb-1">
						<div class="w-full">
							<input
								type="text"
								class="text-left w-full font-semibold text-2xl font-primary bg-transparent outline-hidden"
								bind:value={knowledge.name}
								placeholder="Knowledge Name"
								on:input={() => {
									changeDebounceHandler();
								}}
							/>
						</div>

						<div class="self-center shrink-0">
							<button
								class="bg-gray-50 hover:bg-gray-100 text-black dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white transition px-2 py-1 rounded-full flex gap-1 items-center"
								type="button"
								on:click={() => {
									showAccessControlModal = true;
								}}
							>
								<LockClosed strokeWidth="2.5" className="size-3.5" />

								<div class="text-sm font-medium shrink-0">
									{$i18n.t('Access')}
								</div>
							</button>
						</div>
					</div>

					<div class="flex w-full px-1">
						<input
							type="text"
							class="text-left text-xs w-full text-gray-500 bg-transparent outline-hidden"
							bind:value={knowledge.description}
							placeholder="Knowledge Description"
							on:input={() => {
								changeDebounceHandler();
							}}
						/>
					</div>
				</div>
			</div>
		</div>

		<div class="flex flex-row flex-1 h-full max-h-full pb-2.5 gap-3">
			{#if largeScreen}
				<div class="flex-1 flex justify-start w-full h-full max-h-full">
					{#if selectedFile}
						<div class=" flex flex-col w-full h-full max-h-full">
							<div class="shrink-0 mb-2 flex items-center">
								{#if !showSidepanel}
									<div class="-translate-x-2">
										<button
											class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
											on:click={() => {
												pane.expand();
											}}
										>
											<ChevronLeft strokeWidth="2.5" />
										</button>
									</div>
								{/if}

								<div class=" flex-1 text-xl font-medium">
									<a
										class="hover:text-gray-500 dark:hover:text-gray-100 hover:underline grow line-clamp-1"
										href={selectedFile.id ? `/api/v1/files/${selectedFile.id}/content` : '#'}
										target="_blank"
									>
										{decodeString(selectedFile?.meta?.name)}
									</a>
								</div>

								<div>
									<button
										class="self-center w-fit text-sm py-1 px-2.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-lg"
										on:click={() => {
											updateFileContentHandler();
										}}
									>
										{$i18n.t('Save')}
									</button>
								</div>
							</div>

							<div
								class=" flex-1 w-full h-full max-h-full text-sm bg-transparent outline-hidden overflow-y-auto scrollbar-hidden"
							>
								{#if (selectedFile.meta?.content_type?.startsWith('video/') || selectedFile.meta?.content_type?.startsWith('audio/')) && (!selectedFileContent || selectedFileContent.trim() === '')}
									<div class="flex flex-col items-center justify-center h-full text-center p-8">
										<div class="text-lg font-medium mb-4">
											{$i18n.t('Video/Audio File')}
										</div>
										<div class="text-sm text-gray-500 dark:text-gray-400 mb-6 max-w-md">
											{$i18n.t('This video/audio file needs to be transcribed to extract its content. Click the button below to start transcription.')}
										</div>
										<button
											class="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
											on:click={() => transcribeFileHandler(selectedFile)}
										>
											{$i18n.t('Transcribe File')}
										</button>
									</div>
								{:else}
									{#key selectedFile.id}
										<RichTextInput
											className="input-prose-sm"
											bind:value={selectedFileContent}
											placeholder={$i18n.t('Add content here')}
											preserveBreaks={false}
										/>
									{/key}
								{/if}
							</div>
						</div>
					{:else}
						<div class="h-full flex w-full">
							<div class="m-auto text-xs text-center text-gray-200 dark:text-gray-700">
								{$i18n.t('Drag and drop a file to upload or select a file to view')}
							</div>
						</div>
					{/if}
				</div>
			{:else if !largeScreen && selectedFileId !== null}
				<Drawer
					className="h-full"
					show={selectedFileId !== null}
					onClose={() => {
						selectedFileId = null;
					}}
				>
					<div class="flex flex-col justify-start h-full max-h-full p-2">
						<div class=" flex flex-col w-full h-full max-h-full">
							<div class="shrink-0 mt-1 mb-2 flex items-center">
								<div class="mr-2">
									<button
										class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
										on:click={() => {
											selectedFileId = null;
										}}
									>
										<ChevronLeft strokeWidth="2.5" />
									</button>
								</div>
								<div class=" flex-1 text-xl line-clamp-1">
									{selectedFile?.meta?.name}
								</div>

								<div>
									<button
										class="self-center w-fit text-sm py-1 px-2.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-lg"
										on:click={() => {
											updateFileContentHandler();
										}}
									>
										{$i18n.t('Save')}
									</button>
								</div>
							</div>

							<div
								class=" flex-1 w-full h-full max-h-full py-2.5 px-3.5 rounded-lg text-sm bg-transparent overflow-y-auto scrollbar-hidden"
							>
								{#if (selectedFile.meta?.content_type?.startsWith('video/') || selectedFile.meta?.content_type?.startsWith('audio/')) && (!selectedFileContent || selectedFileContent.trim() === '')}
									<div class="flex flex-col items-center justify-center h-full text-center p-8">
										<div class="text-lg font-medium mb-4">
											{$i18n.t('Video/Audio File')}
										</div>
										<div class="text-sm text-gray-500 dark:text-gray-400 mb-6 max-w-md">
											{$i18n.t('This video/audio file needs to be transcribed to extract its content. Click the button below to start transcription.')}
										</div>
										<button
											class="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
											on:click={() => transcribeFileHandler(selectedFile)}
										>
											{$i18n.t('Transcribe File')}
										</button>
									</div>
								{:else}
									{#key selectedFile.id}
										<RichTextInput
											className="input-prose-sm"
											bind:value={selectedFileContent}
											placeholder={$i18n.t('Add content here')}
											preserveBreaks={false}
										/>
									{/key}
								{/if}
							</div>
						</div>
					</div>
				</Drawer>
			{/if}

			<div
				class="{largeScreen ? 'shrink-0 w-72 max-w-72' : 'flex-1'}
			flex
			py-2
			rounded-2xl
			border
			border-gray-50
			h-full
			dark:border-gray-850"
			>
				<div class=" flex flex-col w-full space-x-2 rounded-lg h-full">
					<div class="w-full h-full flex flex-col">
						<div class=" px-3">
							<div class="flex mb-0.5">
								<div class=" self-center ml-1 mr-3">
									<Search />
								</div>
								<input
									class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
									bind:value={query}
									placeholder={$i18n.t('Search Collection')}
									on:focus={() => {
										selectedFileId = null;
									}}
								/>

								<div>
									<AddContentMenu
										on:upload={(e) => {
											if (e.detail.type === 'directory') {
												uploadDirectoryHandler();
											} else if (e.detail.type === 'text') {
												showAddTextContentModal = true;
											} else if (e.detail.type === 'google-drive-file') {
												uploadGoogleDriveFileHandler();
											} else if (e.detail.type === 'google-drive-folder') {
												uploadGoogleDriveFolderHandler();
											} else {
												document.getElementById('files-input').click();
											}
										}}
										on:sync={(e) => {
											showSyncConfirmModal = true;
										}}
									/>
								</div>
							</div>
						</div>

						{#if filteredItems.length > 0}
							<div class=" flex overflow-y-auto h-full w-full scrollbar-hidden text-xs">
								<Files
									small
									files={filteredItems}
									{selectedFileId}
									on:click={(e) => {
										selectedFileId = selectedFileId === e.detail ? null : e.detail;
									}}
									on:delete={(e) => {
										console.log(e.detail);

										selectedFileId = null;
										deleteFileHandler(e.detail);
									}}
								/>
							</div>
						{:else}
							<div class="my-3 flex flex-col justify-center text-center text-gray-500 text-xs">
								<div>
									{$i18n.t('No content found')}
								</div>
							</div>
						{/if}
					</div>
				</div>
			</div>
		</div>
	{:else}
		<Spinner className="size-5" />
	{/if}
</div>
