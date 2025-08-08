import { get } from 'svelte/store';
import { progressStore } from '../stores/progress.js';
import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface ProgressData {
    session_id: string;
    status: 'processing' | 'transcribing' | 'completed' | 'error' | 'not_found';
    progress: number;
    message?: string;
    error?: string;
    total_files: number;
    processed_files: number;
    current_file: string;
    file_list?: string[];
    last_updated: number;
}

export class ProgressPoller {
    private sessionId: string;
    private intervalId: NodeJS.Timeout | null = null;
    private lastUpdateTime: number = 0;
    private isPolling: boolean = false;
    private onComplete?: () => void;
    private onError?: (error: string) => void;
    private maxStaleTime: number = 60000; // 1 minute
    private startupGraceMs: number = 60000; // allow backend to initialize progress for up to 1 minute
    private pollInterval: number = 1000; // 1 second
    private startTimeMs: number = 0;

    constructor(sessionId: string, onComplete?: () => void, onError?: (error: string) => void) {
        this.sessionId = sessionId;
        this.onComplete = onComplete;
        this.onError = onError;
    }

    public async start(): Promise<void> {
        if (this.isPolling) {
            console.log('ProgressPoller: Already polling for session:', this.sessionId);
            return;
        }

        console.log('ProgressPoller: Starting polling for session:', this.sessionId);
        this.isPolling = true;
        this.lastUpdateTime = Date.now();
        this.startTimeMs = Date.now();

        // Start polling immediately
        await this.poll();

        // Set up interval for continuous polling
        this.intervalId = setInterval(async () => {
            if (!this.isPolling) {
                if (this.intervalId) {
                    clearInterval(this.intervalId);
                    this.intervalId = null;
                }
                return;
            }
            await this.poll();
        }, this.pollInterval);
    }

    public stop(): void {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
        this.isPolling = false;
        console.log('ProgressPoller: Stopped polling for session:', this.sessionId);
    }

    private async poll(): Promise<void> {
        console.log('ProgressPoller: Is polling:', this.isPolling);
        if (!this.isPolling) return;
        console.log('ProgressPoller: Polling for session:', this.sessionId);

                       try {
                   const response = await fetch(`${WEBUI_API_BASE_URL}/progress/${this.sessionId}/status`, {
                       method: 'GET',
                       headers: {
                           'Authorization': `Bearer ${localStorage.getItem('token')}`,
                           'Content-Type': 'application/json'
                       }
                   });

            if (!response.ok) {
                if (response.status === 404) {
                    // Treat as not yet initialized during grace period
                    const elapsedSinceStart = Date.now() - this.startTimeMs;
                    if (elapsedSinceStart < this.startupGraceMs) {
                        console.log('ProgressPoller: Session not ready yet (404). Will retry...');
                        return; // keep polling
                    }
                    console.log('ProgressPoller: Session not found after grace period, stopping polling');
                    this.stop();
                    return;
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const progressData: ProgressData = await response.json();
            console.log('ProgressPoller: Received progress update:', progressData);

            // Update last update time
            this.lastUpdateTime = progressData.last_updated * 1000; // Convert to milliseconds

            // Check if progress is stale
            const now = Date.now();
            if (now - this.lastUpdateTime > this.maxStaleTime) {
                console.log('ProgressPoller: Progress is stale, stopping polling');
                this.stop();
                return;
            }

            // Update the progress store
            this.updateProgressStore(progressData);

            // Check if processing is complete
            const allDone = (progressData.total_files ?? 0) > 0 && progressData.processed_files >= progressData.total_files;
            if (progressData.status === 'completed') {
                // Only stop when ALL files are completed
                if (allDone) {
                    console.log('ProgressPoller: Processing completed (all files done)');
                    this.stop();
                    if (this.onComplete) {
                        this.onComplete();
                    }
                } else {
                    console.log('ProgressPoller: File completed, continuing session for remaining files');
                }
            } else if (progressData.status === 'error') {
                console.log('ProgressPoller: Processing failed with error:', progressData.error);
                this.stop();
                if (this.onError) {
                    this.onError(progressData.error || 'Unknown error');
                }
            } else if (allDone) {
                // Fallback: if counters indicate completion, stop even if status wasn't flipped yet
                console.log('ProgressPoller: All files done by counters, stopping');
                this.stop();
                if (this.onComplete) {
                    this.onComplete();
                }
            }

        } catch (error) {
            console.error('ProgressPoller: Error polling progress:', error);
            
            // Check if we should stop polling due to repeated errors
            const now = Date.now();
            if (now - this.lastUpdateTime > this.maxStaleTime) {
                console.log('ProgressPoller: Too many errors, stopping polling');
                this.stop();
                if (this.onError) {
                    this.onError('Failed to get progress updates');
                }
            }
        }
    }

    private updateProgressStore(progressData: ProgressData): void {
        const currentState = get(progressStore);
        
        // Create or update session
            if (!currentState.sessions.has(this.sessionId)) {
            console.log('ProgressPoller: Creating new session:', this.sessionId);
                const seedList = Array.isArray(progressData.file_list) && progressData.file_list.length > 0
                    ? progressData.file_list
                    : (progressData.current_file ? [progressData.current_file] : ['Processing...']);
                progressStore.startSession(
                    this.sessionId,
                    progressData.total_files,
                    seedList
                );
        } else {
            // Ensure total files stays in sync with backend
            const existingSession = currentState.sessions.get(this.sessionId);
            if (existingSession && existingSession.totalFiles !== progressData.total_files) {
                progressStore.updateTotalFiles(this.sessionId, progressData.total_files, progressData.current_file);
            }
        }

        // Update file progress with inferred per-file status
        const rawMsg = progressData.message || '';
        const lowerMsg = rawMsg.toLowerCase();

        let effectiveStatus: 'processing' | 'transcribing' | 'completed' | 'error';
        if (progressData.status === 'error') {
            effectiveStatus = 'error';
        } else if (
            lowerMsg.startsWith('completed') ||
            lowerMsg.startsWith('skipped') ||
            progressData.status === 'completed' ||
            (typeof progressData.progress === 'number' && progressData.progress >= 100)
        ) {
            effectiveStatus = 'completed';
        } else if (progressData.status === 'transcribing') {
            effectiveStatus = 'transcribing';
        } else {
            effectiveStatus = 'processing';
        }

        const name = progressData.current_file;
        const messageIncludesName = !!(name && rawMsg && rawMsg.includes(name));
        const synthesizedMessage = name && !messageIncludesName
            ? (effectiveStatus === 'completed'
                ? `Completed ${name}`
                : effectiveStatus === 'transcribing'
                    ? `Transcribing ${name}`
                    : `Processing ${name}`)
            : rawMsg;

        progressStore.updateFileProgress(this.sessionId, 'current', {
            status: effectiveStatus,
            progress: progressData.progress,
            message: synthesizedMessage,
            error: progressData.error
        });

        // Ensure we have at least two pending items visible when possible
        if (Array.isArray(progressData.file_list) && progressData.file_list.length > 0) {
            progressStore.addPendingFiles(this.sessionId, progressData.file_list);
        }

        // Update processed files count
        progressStore.updateProcessedFiles(this.sessionId, progressData.processed_files);

        // On reloads, reconstruct completed items from counters and file_list
        if (
            Array.isArray(progressData.file_list) &&
            progressData.file_list.length > 0 &&
            typeof progressData.processed_files === 'number' &&
            progressData.processed_files > 0
        ) {
            const countToMark = Math.min(progressData.processed_files, progressData.file_list.length);
            for (let i = 0; i < countToMark; i++) {
                const fname = progressData.file_list[i];
                if (!fname) continue;
                progressStore.updateFileProgress(this.sessionId, 'current', {
                    status: 'completed',
                    progress: 100,
                    message: `Completed ${fname}`
                });
            }
        }
    }

    public isActive(): boolean {
        return this.isPolling;
    }

    public getLastUpdateTime(): number {
        return this.lastUpdateTime;
    }
}

export function startProgressPolling(
    sessionId: string, 
    onComplete?: () => void, 
    onError?: (error: string) => void
): ProgressPoller {
    const poller = new ProgressPoller(sessionId, onComplete, onError);
    poller.start().catch(error => {
        console.error('ProgressPoller: Failed to start polling:', error);
        if (onError) {
            onError('Failed to start progress tracking');
        }
    });
    return poller;
}

// Global poller registry to prevent multiple pollers for the same session
const activePollers = new Map<string, ProgressPoller>();

export function startProgressTracking(
    sessionId: string, 
    onComplete?: () => void, 
    onError?: (error: string) => void
): ProgressPoller {
    // Stop existing poller if any
    const existingPoller = activePollers.get(sessionId);
    if (existingPoller) {
        existingPoller.stop();
        activePollers.delete(sessionId);
    }

    // Create new poller
    const poller = startProgressPolling(sessionId, () => {
        // Clean up on completion
        activePollers.delete(sessionId);
        if (onComplete) {
            onComplete();
        }
    }, (error) => {
        // Clean up on error
        activePollers.delete(sessionId);
        if (onError) {
            onError(error);
        }
    });

    // Register the poller
    activePollers.set(sessionId, poller);
    
    return poller;
}

export function stopProgressTracking(sessionId: string): void {
    const poller = activePollers.get(sessionId);
    if (poller) {
        poller.stop();
        activePollers.delete(sessionId);
    }
}

export function stopAllProgressTracking(): void {
    for (const [sessionId, poller] of activePollers) {
        poller.stop();
    }
    activePollers.clear();
}

// Check for active sessions in the database and resume them
export async function checkAndResumeDatabaseSessions(): Promise<void> {
    try {
        console.log('ProgressPoller: Checking for active sessions in database...');
        
        // Get all knowledge bases that might have active sessions
        const response = await fetch(`${WEBUI_API_BASE_URL}/knowledge/`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            console.error('Failed to fetch knowledge bases for session check');
            return;
        }

        const knowledgeBases = await response.json();
        console.log('ProgressPoller: Found knowledge bases:', knowledgeBases.length);
        
        for (const knowledge of knowledgeBases) {
            console.log('ProgressPoller: Checking knowledge base:', knowledge.id, 'meta:', knowledge.meta);
            
            if (knowledge.meta && knowledge.meta.processing_progress) {
                const progress = knowledge.meta.processing_progress;
                console.log('ProgressPoller: Found processing_progress:', progress);
                
                // Check if session is still active (not completed and not stale)
                const isActive = progress.status === 'processing' || progress.status === 'transcribing';
                const isStale = (Date.now() - progress.last_updated * 1000) > 5 * 60 * 1000; // 5 minutes
                
                console.log('ProgressPoller: Session status - active:', isActive, 'stale:', isStale, 'status:', progress.status, 'last_updated:', progress.last_updated);
                
                if (isActive && !isStale) {
                    console.log('ProgressPoller: Found active session in database:', knowledge.id);
                    
                    // Create session in progress store (prefer full list when available)
                    const fileList = (Array.isArray(progress.file_list) && progress.file_list.length > 0)
                        ? progress.file_list
                        : (progress.current_file ? [progress.current_file] : ['Processing...']);
                    progressStore.startSession(knowledge.id, progress.total_files || 1, fileList);
                    
                    // Resume polling
                    startProgressTracking(knowledge.id, () => {
                        console.log('ProgressPoller: Database session completed:', knowledge.id);
                    }, (error) => {
                        console.error('ProgressPoller: Database session error:', error);
                    });
                } else if (isStale) {
                    console.log('ProgressPoller: Found stale session in database, cleaning up:', knowledge.id);
                    // Clean up stale session
                    await fetch(`${WEBUI_API_BASE_URL}/progress/${knowledge.id}`, {
                        method: 'DELETE',
                        headers: {
                            'Authorization': `Bearer ${localStorage.getItem('token')}`,
                            'Content-Type': 'application/json'
                        }
                    });
                } else {
                    console.log('ProgressPoller: Session not active or already completed:', knowledge.id, 'status:', progress.status);
                }
            } else {
                console.log('ProgressPoller: No processing_progress found in knowledge base:', knowledge.id);
            }
        }
    } catch (error) {
        console.error('ProgressPoller: Error checking database sessions:', error);
    }
}

// Auto-resume polling on page load if there are active sessions
export function resumeProgressTracking(): void {
    const currentState = get(progressStore);
    
    for (const [sessionId, session] of currentState.sessions) {
        // Only resume if session is not completed
        if (session.processedFiles < session.totalFiles) {
            console.log('ProgressPoller: Resuming polling for session:', sessionId);
            startProgressTracking(sessionId);
        }
    }
}

// Initialize auto-resume when the module loads
if (typeof window !== 'undefined') {
    // Wait for the page to load and check for database sessions
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', async () => {
            await checkAndResumeDatabaseSessions();
            resumeProgressTracking();
        });
    } else {
        checkAndResumeDatabaseSessions().then(() => {
            resumeProgressTracking();
        });
    }
} 