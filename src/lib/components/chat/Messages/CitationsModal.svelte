<script lang="ts">
	import { getContext, onMount, tick, onDestroy } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import VideoPlayer from './VideoPlayer.svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';

	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let citation;
	export let showPercentage = false;
	export let showRelevance = true;

	let mergedDocuments = [];

	function calculatePercentage(distance: number) {
		if (typeof distance !== 'number') return null;
		if (distance < 0) return 0;
		if (distance > 1) return 100;
		return Math.round(distance * 10000) / 100;
	}

	function getRelevanceColor(percentage: number) {
		if (percentage >= 80)
			return 'bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200';
		if (percentage >= 60)
			return 'bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200';
		if (percentage >= 40)
			return 'bg-orange-200 dark:bg-orange-800 text-orange-800 dark:text-orange-200';
		return 'bg-red-200 dark:bg-red-800 text-red-800 dark:text-red-200';
	}

	function formatTimestamp(seconds: number): string {
		const minutes = Math.floor(seconds / 60);
		const remainingSeconds = Math.floor(seconds % 60);
		return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
	}

	function hasTimestampInfo(document: any): boolean {
		return document.metadata?.timestamp_start !== undefined && document.metadata?.timestamp_end !== undefined;
	}

	function isAudioFile(document: any): boolean {
		const contentType = document.metadata?.content_type || '';
		const fileName = document.metadata?.name || '';
		
		return contentType.startsWith('audio/') || 
			   fileName.toLowerCase().match(/\.(mp3|wav|ogg|m4a|webm|flac|aac)$/);
	}

	function isVideoFile(document: any): boolean {
		const contentType = document.metadata?.content_type || '';
		const fileName = document.metadata?.name || '';
		
		return contentType.startsWith('video/') || 
			   fileName.toLowerCase().match(/\.(mp4|webm|avi|mov|mkv|flv|wmv|3gp|ogv)$/);
	}

	function playAudioSegment(fileId: string, startTime: number, endTime: number) {
		const audioElement = document.getElementById(`audio-${fileId}`) as HTMLAudioElement;
		if (audioElement) {
			audioElement.currentTime = startTime;
			audioElement.play();
			
			// Auto-pause at end time if specified
			const timeUpdateHandler = () => {
				if (audioElement.currentTime >= endTime) {
					audioElement.pause();
					audioElement.removeEventListener('timeupdate', timeUpdateHandler);
				}
			};
			audioElement.addEventListener('timeupdate', timeUpdateHandler);
		}
	}

	function jumpToAudioTime(fileId: string, time: number) {
		const audioElement = document.getElementById(`audio-${fileId}`) as HTMLAudioElement;
		if (audioElement) {
			audioElement.currentTime = time;
		}
	}

	function jumpToTimestamp(startTime: number, endTime: number) {
		// This function is used for the timestamp button in the source section
		// It will trigger a custom event that the video/audio player can listen to
		window.dispatchEvent(new CustomEvent('timestampClick', {
			detail: {
				start: startTime,
				end: endTime,
				source: { id: 'citation-modal' }
			}
		}));
	}

	$: if (citation) {
		mergedDocuments = citation.document?.map((c, i) => {
			return {
				source: citation.source,
				document: c,
				metadata: citation.metadata?.[i],
				distance: citation.distances?.[i]
			};
		});
		if (mergedDocuments.every((doc) => doc.distance !== undefined)) {
			mergedDocuments = mergedDocuments.sort(
				(a, b) => (b.distance ?? Infinity) - (a.distance ?? Infinity)
			);
		}
	}

	// Listen for timestamp click events for audio elements
	function handleTimestampClick(event: CustomEvent) {
		const { start, end, source } = event.detail;
		// Handle audio elements in the modal
		mergedDocuments.forEach((doc) => {
			if (isAudioFile(doc) && doc.metadata?.file_id) {
				const audioElement = document.getElementById(`audio-${doc.metadata.file_id}`) as HTMLAudioElement;
				if (audioElement) {
					playAudioSegment(doc.metadata.file_id, start, end);
				}
			}
		});
	}

	onMount(() => {
		window.addEventListener('timestampClick', handleTimestampClick);
	});

	onDestroy(() => {
		window.removeEventListener('timestampClick', handleTimestampClick);
	});

	const decodeString = (str: string) => {
		try {
			return decodeURIComponent(str);
		} catch (e) {
			return str;
		}
	};
</script>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class=" text-lg font-medium self-center capitalize">
				{$i18n.t('Citation')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-5'} />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-6 pb-5 md:space-x-4">
			<div
				class="flex flex-col w-full dark:text-gray-200 overflow-y-scroll max-h-[22rem] scrollbar-hidden"
			>
				{#each mergedDocuments as document, documentIdx}
					<div class="flex flex-col w-full">
						<div class="text-sm font-medium dark:text-gray-300">
							{$i18n.t('Source')}
						</div>

						{#if document.source?.name}
							<Tooltip
								className="w-fit"
								content={$i18n.t('Open file')}
								placement="top-start"
								tippyOptions={{ duration: [500, 0] }}
							>
								<div class="text-sm dark:text-gray-400 flex items-center gap-2 w-fit">
									<a
										class="hover:text-gray-500 dark:hover:text-gray-100 underline grow"
										href={document?.metadata?.file_id
											? `${WEBUI_API_BASE_URL}/files/${document?.metadata?.file_id}/content${document?.metadata?.page !== undefined ? `#page=${document.metadata.page + 1}` : ''}`
											: document.source?.url?.includes('http')
												? document.source.url
												: `#`}
										target="_blank"
									>
										{decodeString(document?.metadata?.name ?? document.source.name)}
									</a>
									{#if Number.isInteger(document?.metadata?.page)}
										<span class="text-xs text-gray-500 dark:text-gray-400">
											({$i18n.t('page')}
											{document.metadata.page + 1})
										</span>
									{/if}
									{#if hasTimestampInfo(document)}
										<span class="text-xs text-blue-600 dark:text-blue-400 ml-2">
											({formatTimestamp(document.metadata.timestamp_start)} - {formatTimestamp(document.metadata.timestamp_end)})
										</span>
										<button
											class="ml-2 p-1 text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 transition rounded"
											on:click={() => jumpToTimestamp(document.metadata.timestamp_start, document.metadata.timestamp_end)}
											title="Jump to timestamp"
										>
											▶ {$i18n.t('Play')}
										</button>
									{/if}
								</div>
							</Tooltip>
							{#if document.metadata?.parameters}
								<div class="text-sm font-medium dark:text-gray-300 mt-2">
									{$i18n.t('Parameters')}
								</div>
								<pre
									class="text-sm dark:text-gray-400 bg-gray-50 dark:bg-gray-800 p-2 rounded-md overflow-auto max-h-40">{JSON.stringify(
										document.metadata.parameters,
										null,
										2
									)}</pre>
							{/if}
							{#if showRelevance}
								<div class="text-sm font-medium dark:text-gray-300 mt-2">
									{$i18n.t('Relevance')}
								</div>
								{#if document.distance !== undefined}
									<Tooltip
										className="w-fit"
										content={$i18n.t('Semantic distance to query')}
										placement="top-start"
										tippyOptions={{ duration: [500, 0] }}
									>
										<div class="text-sm my-1 dark:text-gray-400 flex items-center gap-2 w-fit">
											{#if showPercentage}
												{@const percentage = calculatePercentage(document.distance)}

												{#if typeof percentage === 'number'}
													<span
														class={`px-1 rounded-sm font-medium ${getRelevanceColor(percentage)}`}
													>
														{percentage.toFixed(2)}%
													</span>
												{/if}

												{#if typeof document?.distance === 'number'}
													<span class="text-gray-500 dark:text-gray-500">
														({(document?.distance ?? 0).toFixed(4)})
													</span>
												{/if}
											{:else if typeof document?.distance === 'number'}
												<span class="text-gray-500 dark:text-gray-500">
													({(document?.distance ?? 0).toFixed(4)})
												</span>
											{/if}
										</div>
									</Tooltip>
								{:else}
									<div class="text-sm dark:text-gray-400">
										{$i18n.t('No distance available')}
									</div>
								{/if}
							{/if}
						{:else}
							<div class="text-sm dark:text-gray-400">
								{$i18n.t('No source available')}
							</div>
						{/if}
					</div>
					{#if hasTimestampInfo(document) && document?.metadata?.file_id}
						<div class="text-sm font-medium dark:text-gray-300 mt-2">
							{#if isAudioFile(document)}
								Audio Player
							{:else if isVideoFile(document)}
								Video Player
							{:else}
								Media Player
							{/if}
						</div>
						{#if isAudioFile(document)}
							<div class="audio-player-container">
								<div class="audio-controls mb-2 flex items-center gap-2">
									<button
										class="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition"
										on:click={() => playAudioSegment(document.metadata.file_id, document.metadata.timestamp_start, document.metadata.timestamp_end)}
									>
										▶ Play Segment ({formatTimestamp(document.metadata.timestamp_start)} - {formatTimestamp(document.metadata.timestamp_end)})
									</button>
									<button
										class="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 transition"
										on:click={() => jumpToAudioTime(document.metadata.file_id, document.metadata.timestamp_start)}
									>
										⏭ Jump to {formatTimestamp(document.metadata.timestamp_start)}
									</button>
									{#if document.metadata.timestamp_end}
										<button
											class="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 transition"
											on:click={() => jumpToAudioTime(document.metadata.file_id, document.metadata.timestamp_end)}
										>
											⏭ Jump to {formatTimestamp(document.metadata.timestamp_end)}
										</button>
									{/if}
								</div>
								<audio
									id="audio-{document.metadata.file_id}"
									class="w-full"
									controls
									preload="metadata"
									src={`${WEBUI_API_BASE_URL}/files/${document.metadata.file_id}/content`}
								>
									Your browser does not support the audio tag.
								</audio>
								<div class="audio-info mt-2 text-sm text-gray-600 dark:text-gray-400">
									<div>Segment: {formatTimestamp(document.metadata.timestamp_start)} - {formatTimestamp(document.metadata.timestamp_end)}</div>
									{#if document.metadata.timestamp_end}
										<div>Segment Duration: {formatTimestamp(document.metadata.timestamp_end - document.metadata.timestamp_start)}</div>
									{/if}
								</div>
							</div>
						{:else if isVideoFile(document)}
							<VideoPlayer
								fileId={document.metadata.file_id}
								startTime={document.metadata.timestamp_start}
								endTime={document.metadata.timestamp_end}
								autoPlay={false}
							/>
						{:else}
							<VideoPlayer
								fileId={document.metadata.file_id}
								startTime={document.metadata.timestamp_start}
								endTime={document.metadata.timestamp_end}
								autoPlay={false}
							/>
						{/if}
					{/if}
					<div class="flex flex-col w-full">
						<div class=" text-sm font-medium dark:text-gray-300 mt-2">
							{$i18n.t('Content')}
						</div>
						{#if document.metadata?.html}
							<iframe
								class="w-full border-0 h-auto rounded-none"
								sandbox="allow-scripts allow-forms allow-same-origin"
								srcdoc={document.document}
								title={$i18n.t('Content')}
							></iframe>
						{:else}
							<pre class="text-sm dark:text-gray-400 whitespace-pre-line">
                {document.document}
              </pre>
						{/if}
					</div>

					{#if documentIdx !== mergedDocuments.length - 1}
						<hr class="border-gray-100 dark:border-gray-850 my-3" />
					{/if}
				{/each}
			</div>
		</div>
	</div>
</Modal>

<style>
	.audio-player-container {
		max-width: 100%;
	}
	
	.audio-player-container audio {
		border-radius: 0.375rem;
	}
</style>
