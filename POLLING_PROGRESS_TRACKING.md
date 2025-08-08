# Polling-Based Progress Tracking

This document describes the new polling-based progress tracking system that replaces Server-Sent Events (SSE) for long-running operations like file transcription.

## Overview

The polling progress tracking system replaces SSE-based progress updates for long-running operations, providing better reliability and user experience when users navigate between pages during processing.

## Key Changes

### Backend Changes

1. **Database Storage**: Progress tracking moved from in-memory storage to database storage using the `knowledge` table's `meta` field
2. **Progress Functions**: Updated `update_progress`, `get_progress`, `mark_session_complete`, `mark_session_error` to work with database
3. **New Function**: Added `update_file_progress` for file-specific progress updates
4. **API Endpoints**: 
   - SSE endpoint now returns deprecated message
   - Enhanced status endpoint for polling
   - Added cleanup endpoint

### Frontend Changes

1. **New Polling Utility**: Created `src/lib/utils/polling.ts` to replace SSE tracking
2. **Polling Logic**: 1-second intervals, stops if no updates for 1 minute
3. **Auto-resume**: Automatically resumes polling on page reload if progress is not completed
4. **Updated Components**: KnowledgeBase component now uses polling instead of SSE

## Database Schema

Progress data is stored in the `knowledge` table's `meta` field:

```json
{
  "processing_progress": {
    "session_id": "uuid",
    "status": "processing|completed|error",
    "total_files": 1,
    "processed_files": 0,
    "current_file": "filename",
    "progress": 0,
    "message": "Processing...",
    "last_updated": 1234567890,
    "error": null
  }
}
```

## API Endpoints

### GET `/api/v1/progress/{session_id}/status`
Get current status of a session (for polling)

**Response:**
```json
{
  "session_id": "uuid",
  "status": "processing",
  "progress": 50,
  "message": "Processing file content",
  "total_files": 1,
  "processed_files": 0,
  "current_file": "example.pdf",
  "last_updated": 1234567890
}
```

### DELETE `/api/v1/progress/{session_id}`
Clear progress data for a session

**Response:**
```json
{
  "message": "Progress data cleared successfully"
}
```

### GET `/api/v1/progress/{session_id}` (Legacy)
Returns deprecated message directing to use polling endpoint

## Frontend Usage

### Starting Progress Tracking

```typescript
import { startProgressTracking } from '$lib/utils/polling.js';

const poller = startProgressTracking(sessionId, () => {
    // Called when processing completes
    console.log('Processing completed');
}, (error) => {
    // Called when processing fails
    console.error('Processing failed:', error);
});
```

### Manual Polling

```typescript
import { ProgressPoller } from '$lib/utils/polling.js';

const poller = new ProgressPoller(sessionId, onComplete, onError);
await poller.start();
```

### Stopping Progress Tracking

```typescript
import { stopProgressTracking } from '$lib/utils/polling.js';

stopProgressTracking(sessionId);
```

## Features

- ✅ **Real-time progress updates** via polling (1-second intervals)
- ✅ **Automatic cleanup** of stale progress data (5 minutes)
- ✅ **Persistent progress tracking** across page navigation
- ✅ **Multiple tab support** - progress visible in all tabs
- ✅ **Automatic resume** on page reload
- ✅ **Error handling** with detailed error messages
- ✅ **Database storage** instead of memory storage

## Migration from SSE

### Backend Migration

1. **Progress Storage**: In-memory `progress_store` dict replaced with database storage
2. **Function Updates**: All progress functions updated to work with database
3. **API Changes**: SSE endpoint deprecated, polling endpoint enhanced

### Frontend Migration

1. **Import Changes**: Replace `$lib/utils/sse.js` with `$lib/utils/polling.js`
2. **Function Changes**: `startProgressTracking` now takes separate `onComplete` and `onError` callbacks
3. **Component Updates**: KnowledgeBase component updated to use polling

## Configuration

### Polling Settings

- **Poll Interval**: 1 second (configurable in `ProgressPoller` class)
- **Stale Timeout**: 1 minute (configurable in `ProgressPoller` class)
- **Backend Stale Timeout**: 5 minutes (configurable in `get_progress` function)

### Database Settings

- **Storage**: Uses existing `knowledge` table's `meta` field
- **Cleanup**: Automatic cleanup of stale progress data
- **Persistence**: Progress survives server restarts

## Testing

Use the provided test script to verify the implementation:

```bash
python test_polling.py
```

## Benefits

1. **Reliability**: No connection drops or reconnection issues
2. **Simplicity**: Standard HTTP requests instead of SSE
3. **Persistence**: Progress survives server restarts
4. **Scalability**: Database storage instead of memory
5. **Compatibility**: Works with all browsers and network configurations

## Future Enhancements

1. **Redis Integration**: Move to Redis for better performance
2. **WebSocket Support**: Add WebSocket option for real-time updates
3. **Batch Processing**: Support for multiple file processing
4. **Progress History**: Store progress history for analytics 