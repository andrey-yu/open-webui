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
					startTime: Date.now()
				};
				
				const newSessions = new Map(state.sessions);
				newSessions.set(sessionId, session);
				
				console.log('Progress store: Session created', session);
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
				const session = state.sessions.get(sessionId);
				if (!session) {
					console.warn('Progress store: Session not found', sessionId);
					return state;
				}

				let updatedFiles;
				
				// For single file processing, update the first file regardless of fileId
				if (session.files.length === 1) {
					updatedFiles = session.files.map(file => ({ ...file, ...updates }));
				} else {
					// For batch processing, try to match by file ID first
					const fileIndex = session.files.findIndex(file => file.id === fileId);
					
					if (fileIndex !== -1) {
						// Found by ID, update that specific file
						updatedFiles = session.files.map((file, index) => 
							index === fileIndex ? { ...file, ...updates } : file
						);
					} else {
						// ID not found, try to match by filename from the message
						// This handles the case where backend sends different IDs than frontend expects
						const message = updates.message || '';
						const filename = message.match(/Downloading (.+)$/)?.[1] || 
										message.match(/Uploading (.+)$/)?.[1] || 
										message.match(/Creating file record for (.+)$/)?.[1] || 
										message.match(/Transcribing (.+)$/)?.[1] || 
										message.match(/Processing audio chunks for (.+)$/)?.[1] ||
										message.match(/Processing (.+)$/)?.[1] ||
										message.match(/Completed (.+)$/)?.[1] ||
										message.match(/Transcription completed for (.+)$/)?.[1];
						
						if (filename) {
							const fileIndex = session.files.findIndex(file => file.filename === filename);
							if (fileIndex !== -1) {
								updatedFiles = session.files.map((file, index) => 
									index === fileIndex ? { ...file, ...updates } : file
								);
							} else {
								// Still not found, update the first file as fallback
								console.warn('Progress store: Could not match file by ID or filename, updating first file as fallback');
								updatedFiles = session.files.map((file, index) => 
									index === 0 ? { ...file, ...updates } : file
								);
							}
						} else {
							// No filename found in message, update the first file as fallback
							console.warn('Progress store: Could not extract filename from message, updating first file as fallback');
							updatedFiles = session.files.map((file, index) => 
								index === 0 ? { ...file, ...updates } : file
							);
						}
					}
				}

				const processedFiles = updatedFiles.filter(f => f.status === 'completed').length;
				const newSession = {
					...session,
					files: updatedFiles,
					processedFiles
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

export const progressStore = createProgressStore(); 