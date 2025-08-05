# Server-Sent Events (SSE) Progress Tracking

This document describes the new Server-Sent Events (SSE) progress tracking system implemented for long-running operations like file transcription.

## Overview

The SSE progress tracking system replaces WebSocket-based progress updates for long-running operations, providing better reliability and user experience when users navigate between pages during processing.

## Features

- ✅ **Real-time progress updates** via Server-Sent Events
- ✅ **Automatic reconnection** when connection is lost
- ✅ **Persistent progress tracking** across page navigation
- ✅ **Multiple tab support** - progress visible in all tabs
- ✅ **Automatic cleanup** of completed sessions
- ✅ **Error handling** with detailed error messages

## How It Works

### Backend (Python)

1. **Progress Storage**: Progress is stored in memory (can be moved to Redis/database for production)
2. **SSE Endpoint**: `/api/v1/progress/{session_id}` streams progress updates
3. **Session Management**: Sessions are automatically cleaned up when completed

### Frontend (TypeScript/Svelte)

1. **SSE Client**: `ProgressTracker` class manages SSE connections
2. **Auto-reconnection**: Automatically reconnects if connection is lost
3. **Progress Store Integration**: Updates the existing progress store
4. **Navigation Support**: Progress continues when navigating away and back

## Usage

### Starting Progress Tracking

When uploading a file from Google Drive, the API now returns a `session_id`:

```typescript
const result = await addGoogleDriveFileToKnowledge(token, knowledgeId, fileId, oauthToken);
// result.session_id contains the session ID for progress tracking
```

The frontend automatically starts SSE tracking when a `session_id` is returned.

### Manual Progress Tracking

You can also manually start progress tracking:

```typescript
import { startProgressTracking } from '$lib/utils/sse.js';

const tracker = startProgressTracking(sessionId);

// Later, stop tracking
tracker.disconnect();
```

### Progress Updates

Progress updates are automatically handled and displayed in the UI:

- **Processing**: File download, upload, and processing
- **Transcribing**: Audio/video transcription (with detailed progress)
- **Completed**: File successfully processed
- **Error**: Processing failed with error details

## API Endpoints

### SSE Stream
```
GET /api/v1/progress/{session_id}
```
Returns a Server-Sent Events stream with progress updates.

### Status Check (Fallback)
```
GET /api/v1/progress/{session_id}/status
```
Returns current progress status (for polling fallback).

## Benefits Over WebSocket

| Feature | WebSocket | SSE |
|---------|-----------|-----|
| **Connection Loss** | Progress lost on disconnect | Auto-reconnect, resume progress |
| **Page Navigation** | Progress lost when navigating | Progress persists across navigation |
| **Multiple Tabs** | Only one tab shows progress | All tabs show progress |
| **Long Operations** | Connection may timeout | Persistent connection |
| **Error Handling** | Complex reconnection logic | Built-in auto-reconnection |

## Implementation Details

### Backend Components

- `open_webui/routers/progress.py` - SSE endpoint and progress management
- `open_webui/routers/knowledge.py` - Updated to use SSE instead of WebSocket
- `open_webui/main.py` - Progress router registration

### Frontend Components

- `src/lib/utils/sse.ts` - SSE client implementation
- `src/lib/apis/knowledge/index.ts` - Updated to start SSE tracking
- `src/lib/stores/progress.ts` - Existing progress store (unchanged)

## Configuration

The SSE system uses in-memory storage by default. For production deployments, consider:

1. **Redis Storage**: Move progress storage to Redis for multi-instance support
2. **Database Storage**: Store progress in database for persistence
3. **Session Cleanup**: Implement automatic cleanup of old sessions

## Testing

The SSE progress tracking has been tested with:

- ✅ Progress updates during transcription
- ✅ Page navigation during processing
- ✅ Multiple browser tabs
- ✅ Connection loss and reconnection
- ✅ Error handling and recovery

## Future Enhancements

- [ ] Redis-based progress storage for multi-instance deployments
- [ ] Progress persistence across server restarts
- [ ] Batch file processing with individual file progress
- [ ] Progress history and analytics
- [ ] WebSocket fallback for browsers without SSE support 