<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';

	export let fileId: string;
	export let startTime: number = 0;
	export let endTime: number | null = null;
	export let autoPlay: boolean = false;

	let videoElement: HTMLVideoElement;
	let isPlaying = false;
	let currentTime = 0;
	let duration = 0;

	function formatTime(seconds: number): string {
		const minutes = Math.floor(seconds / 60);
		const remainingSeconds = Math.floor(seconds % 60);
		return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
	}

	function jumpToTime(time: number) {
		if (videoElement) {
			videoElement.currentTime = time;
		}
	}

	function playSegment() {
		if (videoElement) {
			videoElement.currentTime = startTime;
			videoElement.play();
		}
	}

	function handleTimeUpdate() {
		if (videoElement) {
			currentTime = videoElement.currentTime;
			
			// Auto-pause at end time if specified
			if (endTime && currentTime >= endTime) {
				videoElement.pause();
			}
		}
	}

	function handleLoadedMetadata() {
		if (videoElement) {
			duration = videoElement.duration;
			if (autoPlay) {
				playSegment();
			}
		}
	}

	function handlePlay() {
		isPlaying = true;
	}

	function handlePause() {
		isPlaying = false;
	}

	// Listen for timestamp click events
	function handleTimestampClick(event: CustomEvent) {
		const { start, end, source } = event.detail;
		// Only handle if this is the target video
		if (source?.id === fileId || source?.name?.includes(fileId)) {
			startTime = start;
			endTime = end;
			playSegment();
		}
	}

	onMount(() => {
		window.addEventListener('timestampClick', handleTimestampClick);
	});

	onDestroy(() => {
		window.removeEventListener('timestampClick', handleTimestampClick);
	});
</script>

<div class="video-player-container">
	<div class="video-controls mb-2 flex items-center gap-2">
		<button
			class="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition"
			on:click={playSegment}
		>
			▶ Play Segment ({formatTime(startTime)} - {endTime ? formatTime(endTime) : 'End'})
		</button>
		<button
			class="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 transition"
			on:click={() => jumpToTime(startTime)}
		>
			⏭ Jump to {formatTime(startTime)}
		</button>
		{#if endTime}
			<button
				class="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 transition"
				on:click={() => jumpToTime(endTime)}
			>
				⏭ Jump to {formatTime(endTime)}
			</button>
		{/if}
	</div>

	<video
		bind:this={videoElement}
		class="w-full rounded-md"
		controls
		preload="metadata"
		src={`${WEBUI_API_BASE_URL}/files/${fileId}/content`}
		on:timeupdate={handleTimeUpdate}
		on:loadedmetadata={handleLoadedMetadata}
		on:play={handlePlay}
		on:pause={handlePause}
	>
		Your browser does not support the video tag.
	</video>

	<div class="video-info mt-2 text-sm text-gray-600 dark:text-gray-400">
		<div>Current Time: {formatTime(currentTime)} / {formatTime(duration)}</div>
		<div>Segment: {formatTime(startTime)} - {endTime ? formatTime(endTime) : formatTime(duration)}</div>
		{#if endTime}
			<div>Segment Duration: {formatTime(endTime - startTime)}</div>
		{/if}
	</div>
</div>

<style>
	.video-player-container {
		max-width: 100%;
	}
</style> 