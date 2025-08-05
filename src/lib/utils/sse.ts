import { get } from 'svelte/store';
import { progressStore } from '../stores/progress.js';

export interface ProgressData {
    session_id: string;
    file_id: string;
    status: 'processing' | 'transcribing' | 'completed' | 'error' | 'not_found';
    progress: number;
    message?: string;
    error?: string;
    total_files: number;
    file_list: string[];
}

export class ProgressTracker {
    private sessionId: string;
    private eventSource: EventSource | null = null;
    private isConnected = false;
    private reconnectAttempts = 0;
    private maxReconnectAttempts = 5;
    private reconnectDelay = 1000; // 1 second
    private stopped = false;

    constructor(sessionId: string) {
        this.sessionId = sessionId;
    }

    public async connect() {
        // Don't connect if the tracker has been stopped
        if (this.stopped) {
            console.log('Tracker stopped, not connecting for session:', this.sessionId);
            return;
        }
        
        // Don't connect if the session is already completed
        const currentState = get(progressStore);
        const session = currentState.sessions.get(this.sessionId);
        if (session && session.files.every(f => f.status === 'completed' || f.status === 'error')) {
            console.log('Session already completed, not connecting:', this.sessionId);
            return;
        }
        
        try {
            // Use the same base URL logic as the rest of the application
            const isDev = import.meta.env.DEV;
            const baseUrl = isDev ? `http://${window.location.hostname}:8083` : window.location.origin;
            const url = `${baseUrl}/api/v1/progress/${this.sessionId}`;
            
            // For SSE, we need to include the auth token in the URL since EventSource doesn't support custom headers
            const token = localStorage.getItem('token');
            const authUrl = token ? `${url}?token=${encodeURIComponent(token)}` : url;
            
            // Create EventSource
            this.eventSource = new EventSource(authUrl);
            
            if (this.eventSource) {
                this.eventSource.onopen = () => {
                    // Don't process if tracker is stopped
                    if (this.stopped) {
                        console.log('Tracker stopped, ignoring onopen event for session:', this.sessionId);
                        return;
                    }
                    
                    console.log('SSE connected for session:', this.sessionId);
                    this.isConnected = true;
                };
            }
            
            if (this.eventSource) {
                this.eventSource.onmessage = (event) => {
                    // Don't process if tracker is stopped
                    if (this.stopped) {
                        console.log('Tracker stopped, ignoring onmessage event for session:', this.sessionId);
                        return;
                    }
                    
                    try {
                        const progress = JSON.parse(event.data);
                        console.log('SSE message received for session:', this.sessionId, progress);
                        
                        // If we receive any message, consider the connection established
                        if (!this.isConnected) {
                            this.isConnected = true;
                        }
                        
                        this.handleProgressUpdate(progress);
                    } catch (error) {
                        console.error('Error parsing SSE message:', error, 'Raw data:', event.data);
                    }
                };
            }
            
            if (this.eventSource) {
                this.eventSource.onerror = (event) => {
                    // Don't process if tracker is stopped
                    if (this.stopped) {
                        console.log('Tracker stopped, ignoring onerror event for session:', this.sessionId);
                        return;
                    }
                    
                    console.log('SSE error for session:', this.sessionId);
                    this.isConnected = false;
                    this.handleReconnection();
                };
            }
        } catch (error) {
            console.error('Error connecting to SSE:', error);
        }
    }

    private handleReconnection() {
        // Don't reconnect if the tracker has been stopped
        if (this.stopped) {
            console.log('Tracker stopped, not reconnecting:', this.sessionId);
            return;
        }
        
        // Don't reconnect if the session is already completed
        const currentState = get(progressStore);
        const session = currentState.sessions.get(this.sessionId);
        if (session && session.files.every(f => f.status === 'completed' || f.status === 'error')) {
            console.log('Session already completed, not reconnecting:', this.sessionId);
            return;
        }
        
        // Auto-reconnect logic
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            setTimeout(async () => {
                // Double-check that we're still not stopped before reconnecting
                if (!this.stopped && this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                    await this.connect();
                }
            }, this.reconnectDelay * this.reconnectAttempts);
        } else {
            console.warn('Max SSE reconnection attempts reached for session:', this.sessionId);
        }
    }

    private handleProgressUpdate(progress: ProgressData) {
        // Don't process updates if tracker has been stopped
        if (this.stopped) {
            console.log('Tracker stopped, ignoring progress update for session:', this.sessionId);
            return;
        }
        
        // Update the progress store
        if (progress.status === 'not_found') {
            console.warn('Session not found:', this.sessionId);
            return;
        }

        // Start session if not already started
        const currentState = get(progressStore);
        
        // Ensure we have the required fields for session creation
        if (!progress.session_id || !progress.total_files || !progress.file_list) {
            console.warn('Missing required fields for session creation:', progress);
            return;
        }
        
        // Create session if it doesn't exist
        if (!currentState.sessions.has(progress.session_id)) {
            console.log('Starting new session:', progress.session_id);
            
            progressStore.startSession(
                progress.session_id,
                progress.total_files,
                progress.file_list
            );
        }

        // Update file progress
        if (!progress.file_id) {
            console.warn('Missing file_id for progress update:', progress);
            return;
        }
        
        progressStore.updateFileProgress(progress.session_id, progress.file_id, {
            status: progress.status,
            progress: progress.progress,
            message: progress.message,
            error: progress.error
        });
        
        // Handle completion
        if (progress.status === 'completed' || progress.status === 'error') {
            console.log('Session completed, stopping tracking for session:', this.sessionId);
            
            // Set stopped flag immediately to prevent any reconnection attempts
            this.stopped = true;
            
            // Immediately close the EventSource to stop receiving messages
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            
            // Call registered completion callbacks immediately to update data
            const callbacks = sessionCompletionCallbacks.get(progress.session_id);
            if (callbacks) {
                callbacks.forEach(callback => {
                    try {
                        callback();
                    } catch (error) {
                        console.error('Error in session completion callback:', error);
                    }
                });
                sessionCompletionCallbacks.delete(progress.session_id);
            }
            
            // Complete the session in the store after a delay to keep it visible in UI
            setTimeout(() => {
                progressStore.completeSession(progress.session_id);
                
                // Now clean up the tracker
                stopProgressTracking(progress.session_id);
            }, 3000); // Keep session visible for 3 seconds
        }
    }

    public disconnect() {
        // Set stopped flag first to prevent any further processing
        this.stopped = true;
        
        // Immediately close the EventSource and remove all event listeners
        if (this.eventSource) {
            // Remove all event listeners to prevent further callbacks
            this.eventSource.onopen = null;
            this.eventSource.onmessage = null;
            this.eventSource.onerror = null;
            
            // Close the connection
            this.eventSource.close();
            this.eventSource = null;
        }
        
        this.isConnected = false;
        
        // Don't automatically complete the session here - let the completion handler control timing
        // The session will be completed by the completion handler after the appropriate delay
    }

    public isConnectedStatus(): boolean {
        return this.isConnected && this.eventSource !== null && this.eventSource.readyState === EventSource.OPEN;
    }
    
    public getReconnectAttempts(): number {
        return this.reconnectAttempts;
    }
    
    public getMaxReconnectAttempts(): number {
        return this.maxReconnectAttempts;
    }
}

// Track multiple sessions
const trackers = new Map<string, ProgressTracker>();

// Callbacks for session completion
const sessionCompletionCallbacks = new Map<string, (() => void)[]>();

export function startProgressTracking(sessionId: string, onComplete?: () => void): Promise<void> {
    return new Promise((resolve, reject) => {
        // If we already have a tracker for this session, don't create a new one
        if (trackers.has(sessionId)) {
            const existingTracker = trackers.get(sessionId);
            if (existingTracker && existingTracker.isConnectedStatus()) {
                resolve();
                return;
            }
        }
        
        // Register completion callback if provided
        if (onComplete) {
            if (!sessionCompletionCallbacks.has(sessionId)) {
                sessionCompletionCallbacks.set(sessionId, []);
            }
            sessionCompletionCallbacks.get(sessionId)!.push(onComplete);
        }
        
        const tracker = new ProgressTracker(sessionId);
        trackers.set(sessionId, tracker);
        
        // Connect immediately but don't block
        tracker.connect().catch(error => {
            console.error('Error connecting tracker:', error);
        });
        
        // Wait for connection to be established with timeout
        const maxWaitTime = 2000; // 2 seconds maximum wait time
        const checkInterval = 100; // Check every 100ms
        const startTime = Date.now();
        
        const checkConnection = () => {
            const elapsed = Date.now() - startTime;
            
            if (tracker.isConnectedStatus()) {
                resolve();
            } else if (tracker.getReconnectAttempts() >= tracker.getMaxReconnectAttempts()) {
                reject(new Error(`SSE connection failed after ${tracker.getMaxReconnectAttempts()} retries for session ${sessionId}`));
            } else if (elapsed >= maxWaitTime) {
                // Resolve anyway since the backend is working and we want to proceed with the upload
                resolve();
            } else {
                // Continue checking
                setTimeout(checkConnection, checkInterval);
            }
        };
        
        // Start checking after a short delay to allow initial connection attempt
        setTimeout(checkConnection, checkInterval);
    });
}

export function stopProgressTracking(sessionId: string) {
    const tracker = trackers.get(sessionId);
    if (tracker) {
        tracker.disconnect();
        trackers.delete(sessionId);
    }
}

export function getProgressTracker(sessionId: string): ProgressTracker | undefined {
    return trackers.get(sessionId);
}

// Clean up all trackers when page unloads
window.addEventListener('beforeunload', () => {
    trackers.forEach(tracker => tracker.disconnect());
    trackers.clear();
}); 