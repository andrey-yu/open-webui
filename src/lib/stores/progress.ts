import { writable } from 'svelte/store';

export interface FileProgress {
	id: string;
	filename: string;
	status: 'pending' | 'processing' | 'transcribing' | 'completed' | 'error';
	progress: number; // 0-100
	message?: string;
	error?: string;
}

export interface ProcessingSession {
	id: string;
	totalFiles: number;
	processedFiles: number;
	files: FileProgress[];
	startTime: number;
	estimatedTimeRemaining?: number;
	currentProcessingFileIndex?: number; // Track which file is currently being processed
}

interface ProgressState {
	sessions: Map<string, ProcessingSession>;
	activeSessionId: string | null;
}

function createProgressStore() {
	const { subscribe, set, update } = writable<ProgressState>({
		sessions: new Map(),
		activeSessionId: null
	});

	return {
		subscribe,
		
		// Start a new processing session
		startSession: (sessionId: string, totalFiles: number, fileList: string[]) => {
			console.log('Progress store: Starting session', { sessionId, totalFiles, fileList });
			update(state => {
				const session: ProcessingSession = {
					id: sessionId,
					totalFiles,
					processedFiles: 0,
					files: fileList.map(filename => ({
						id: crypto.randomUUID(),
						filename,
						status: 'pending' as const,
						progress: 0
					})),
					startTime: Date.now(),
					currentProcessingFileIndex: 0
				};
				
				const newSessions = new Map(state.sessions);
				newSessions.set(sessionId, session);
				
				console.log('Progress store: Session created', session);
				console.log('Progress store: Session files:', session.files.map(f => ({ id: f.id, filename: f.filename, status: f.status })));
				console.log('Progress store: Total sessions after creation:', newSessions.size);
				
				return {
					sessions: newSessions,
					activeSessionId: sessionId
				};
			});
		},

		// Update file progress
		updateFileProgress: (sessionId: string, fileId: string, updates: Partial<FileProgress>) => {
			console.log('Progress store: Updating file progress', { sessionId, fileId, updates });
			update(state => {
				console.log('Progress store: Current state sessions:', Array.from(state.sessions.keys()));
				const session = state.sessions.get(sessionId);
				if (!session) {
					console.warn('Progress store: Session not found', sessionId);
					return state;
				}

				let updatedFiles;
				let fileMatched = false;
				let matchedFileIndex = -1;
				
				// For single file processing, update the first file regardless of fileId
				if (session.files.length === 1) {
					updatedFiles = session.files.map(file => ({ ...file, ...updates }));
					fileMatched = true;
					matchedFileIndex = 0;
					console.log('Progress store: Single file processing - updated first file');
				} else {
					// For batch processing, try to match by file ID first
					const fileIndex = session.files.findIndex(file => file.id === fileId);
					
					if (fileIndex !== -1) {
						// Found by ID, update that specific file
						updatedFiles = session.files.map((file, index) => 
							index === fileIndex ? { ...file, ...updates } : file
						);
						fileMatched = true;
						matchedFileIndex = fileIndex;
						console.log('Progress store: File matched by ID at index', fileIndex);
					} else {
						// ID not found, try to match by filename from the message
						// This handles the case where backend sends different IDs than frontend expects
						const message = updates.message || '';
						const filename = extractFilenameFromMessage(message);
						
						if (filename) {
							console.log('Progress store: Extracted filename from message:', filename);
							console.log('Progress store: Available filenames in session:', session.files.map(f => f.filename));
							
							const fileIndex = session.files.findIndex(file => file.filename === filename);
							if (fileIndex !== -1) {
								updatedFiles = session.files.map((file, index) => 
									index === fileIndex ? { ...file, ...updates } : file
								);
								fileMatched = true;
								matchedFileIndex = fileIndex;
								console.log('Progress store: File matched by filename at index', fileIndex, 'filename:', filename);
							} else {
								console.warn('Progress store: Filename not found in session files:', filename);
								console.log('Progress store: Available filenames:', session.files.map(f => f.filename));
								console.log('Progress store: Exact match failed, checking for partial matches...');
								
								// Try partial matching as fallback
								const partialMatchIndex = session.files.findIndex(file => 
									filename.includes(file.filename) || file.filename.includes(filename)
								);
								if (partialMatchIndex !== -1) {
									updatedFiles = session.files.map((file, index) => 
										index === partialMatchIndex ? { ...file, ...updates } : file
									);
									fileMatched = true;
									matchedFileIndex = partialMatchIndex;
									console.log('Progress store: File matched by partial filename at index', partialMatchIndex, 'filename:', session.files[partialMatchIndex].filename);
								}
							}
						} else {
							console.warn('Progress store: Could not extract filename from message:', message);
						}
						
						// If still not matched, try to update the next pending file
						if (!fileMatched) {
							console.log('Progress store: Attempting fallback matching strategies...');
							console.log('Progress store: Current session files:', session.files.map(f => ({ filename: f.filename, status: f.status, progress: f.progress })));
							
							// First, try to find a file that's currently processing
							const processingIndex = session.files.findIndex(file => 
								file.status === 'processing' || file.status === 'transcribing'
							);
							if (processingIndex !== -1) {
								updatedFiles = session.files.map((file, index) => 
									index === processingIndex ? { ...file, ...updates } : file
								);
								fileMatched = true;
								matchedFileIndex = processingIndex;
								console.log('Progress store: Updated currently processing file at index', processingIndex, 'filename:', session.files[processingIndex].filename);
							} else {
								// Try to find the next pending file
								const nextPendingIndex = session.files.findIndex(file => file.status === 'pending');
								if (nextPendingIndex !== -1) {
									updatedFiles = session.files.map((file, index) => 
										index === nextPendingIndex ? { ...file, ...updates } : file
									);
									fileMatched = true;
									matchedFileIndex = nextPendingIndex;
									console.log('Progress store: Updated next pending file at index', nextPendingIndex, 'filename:', session.files[nextPendingIndex].filename);
								} else {
									// Last resort: update the first file as fallback
									console.warn('Progress store: No pending or processing files found, updating first file as fallback');
									updatedFiles = session.files.map((file, index) => 
										index === 0 ? { ...file, ...updates } : file
									);
									fileMatched = true;
									matchedFileIndex = 0;
								}
							}
						}
					}
				}

				// Ensure updatedFiles is defined before using it
				if (!updatedFiles) {
					console.warn('Progress store: No file was matched, using original files');
					updatedFiles = session.files;
				}

				const processedFiles = updatedFiles.filter(f => f.status === 'completed').length;
				const newSession = {
					...session,
					files: updatedFiles,
					processedFiles,
					currentProcessingFileIndex: matchedFileIndex !== -1 ? matchedFileIndex : session.currentProcessingFileIndex
				};

				const newSessions = new Map(state.sessions);
				newSessions.set(sessionId, newSession);

				console.log('Progress store: File progress updated', { sessionId, fileId, newSession });
				console.log('Progress store: Total sessions after update:', newSessions.size);

				return {
					...state,
					sessions: newSessions
				};
			});
		},

		// Update filename for a file in a session
		updateFilename: (sessionId: string, fileId: string, filename: string) => {
			console.log('Progress store: Updating filename', { sessionId, fileId, filename });
			update(state => {
				const session = state.sessions.get(sessionId);
				if (!session) {
					console.warn('Progress store: Session not found', sessionId);
					return state;
				}

				let updatedFiles;
				
				// For single file processing, update the first file regardless of fileId
				if (session.files.length === 1) {
					updatedFiles = session.files.map(file => ({ ...file, filename }));
				} else {
					// For batch processing, match by file ID
					updatedFiles = session.files.map(file => 
						file.id === fileId ? { ...file, filename } : file
					);
				}

				const newSession = {
					...session,
					files: updatedFiles
				};

				const newSessions = new Map(state.sessions);
				newSessions.set(sessionId, newSession);

				console.log('Progress store: Filename updated', { sessionId, fileId, filename });

				return {
					...state,
					sessions: newSessions
				};
			});
		},

		// Complete a session
		completeSession: (sessionId: string) => {
			update(state => {
				const newSessions = new Map(state.sessions);
				newSessions.delete(sessionId);
				
				return {
					sessions: newSessions,
					activeSessionId: state.activeSessionId === sessionId ? null : state.activeSessionId
				};
			});
		},

		// Update processed files count
		updateProcessedFiles: (sessionId: string, processedFiles: number) => {
			console.log('Progress store: Updating processed files count', { sessionId, processedFiles });
			update(state => {
				const session = state.sessions.get(sessionId);
				if (!session) {
					console.warn('Progress store: Session not found', sessionId);
					return state;
				}

				const newSession = {
					...session,
					processedFiles
				};

				const newSessions = new Map(state.sessions);
				newSessions.set(sessionId, newSession);

				console.log('Progress store: Processed files count updated', { sessionId, processedFiles });

				return {
					...state,
					sessions: newSessions
				};
			});
		},

		// Ensure session has placeholders for a given list of filenames
		addPendingFiles: (sessionId: string, fileList: string[]) => {
			console.log('Progress store: Ensuring pending files', { sessionId, fileList });
			update(state => {
				const session = state.sessions.get(sessionId);
				if (!session) {
					console.warn('Progress store: Session not found', sessionId);
					return state;
				}

				const existingFilenames = new Set(session.files.map(f => f.filename));
				const newFiles: FileProgress[] = [];
				for (const name of fileList) {
					if (!existingFilenames.has(name)) {
						newFiles.push({
							id: crypto.randomUUID(),
							filename: name,
							status: 'pending',
							progress: 0
						});
					}
				}

				if (newFiles.length === 0) {
					return state;
				}

				const newSession: ProcessingSession = {
					...session,
					files: [...session.files, ...newFiles]
				};
				const newSessions = new Map(state.sessions);
				newSessions.set(sessionId, newSession);
				return {
					...state,
					sessions: newSessions
				};
			});
		},

		// Update total files count
		updateTotalFiles: (sessionId: string, totalFiles: number, currentFileName?: string) => {
			console.log('Progress store: Updating total files count', { sessionId, totalFiles, currentFileName });
			update(state => {
				const session = state.sessions.get(sessionId);
				if (!session) {
					console.warn('Progress store: Session not found', sessionId);
					return state;
				}

				const newSession = { ...session };
				newSession.totalFiles = totalFiles;

				// Optionally update the first file's name if we have a better current file
				if (currentFileName && newSession.files.length === 1 && newSession.files[0].filename !== currentFileName) {
					newSession.files = newSession.files.map((f, idx) => idx === 0 ? { ...f, filename: currentFileName } : f);
				}

				const newSessions = new Map(state.sessions);
				newSessions.set(sessionId, newSession);

				return {
					...state,
					sessions: newSessions
				};
			});
		},

		// Get current session
		getCurrentSession: (state: ProgressState) => {
			return state.activeSessionId ? state.sessions.get(state.activeSessionId) : null;
		},

		// Clear all sessions
		clear: () => {
			set({
				sessions: new Map(),
				activeSessionId: null
			});
		}
	};
}

// Helper function to extract filename from progress message
function extractFilenameFromMessage(message: string): string | null {
	const patterns = [
		/Downloading (.+)$/,
		/Uploading (.+)$/,
		/Creating file record for (.+)$/,
		/Transcribing (.+)$/,
		/Processing audio chunks for (.+)$/,
		/Processing (.+)$/,
		/Completed (.+)$/,
		/Transcription completed for (.+)$/,
		/Transcribing (.+?)\.\.\./,
		/Processing (.+?)\.\.\./
	];
	
	for (const pattern of patterns) {
		const match = message.match(pattern);
		if (match && match[1]) {
			// Clean up the filename by removing any trailing text after the filename
			let filename = match[1];
			// Remove any text after the file extension (like "... (6s elapsed)")
			filename = filename.replace(/\s*\.\.\.\s*\(.*\)$/, '');
			return filename;
		}
	}
	
	return null;
}

export const progressStore = createProgressStore(); 