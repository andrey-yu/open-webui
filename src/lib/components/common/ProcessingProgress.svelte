<script lang="ts">
	import { progressStore, type ProcessingSession } from '$lib/stores/progress';
	import { getContext } from 'svelte';
	import { onMount, onDestroy } from 'svelte';
	
	const i18n = getContext('i18n');
	
	import Spinner from './Spinner.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import CheckCircle from '$lib/components/icons/CheckCircle.svelte';
	import Document from '$lib/components/icons/Document.svelte';
	import Mic from '$lib/components/icons/Mic.svelte';

	export let sessionId: string;
	
	let session: ProcessingSession | undefined;
	let unsubscribe: () => void;
	
	onMount(() => {
		console.log('ProcessingProgress: Mounting for session:', sessionId);
		unsubscribe = progressStore.subscribe(state => {
			session = state.sessions.get(sessionId);
			console.log('ProcessingProgress: Session update for', sessionId, ':', session);
		});
	});
	
	onDestroy(() => {
		if (unsubscribe) unsubscribe();
	});
	
	$: if (session) {
		const elapsed = Date.now() - session.startTime;
		const avgTimePerFile = session.processedFiles > 0 ? elapsed / session.processedFiles : 0;
		const remainingFiles = session.totalFiles - session.processedFiles;
		const estimatedTimeRemaining = avgTimePerFile * remainingFiles;
	}
	
		const getStatusIcon = (status: string) => {
		switch (status) {
			case 'pending':
				return Document;
			case 'processing':
				return Document;
			case 'transcribing':
				return Mic;
			case 'completed':
				return CheckCircle;
			case 'error':
				return XMark;
			default:
				return Document;
		}
	};
	
	const getStatusColor = (status: string) => {
		switch (status) {
			case 'pending':
				return 'text-gray-500';
			case 'processing':
				return 'text-blue-500';
			case 'transcribing':
				return 'text-purple-500';
			case 'completed':
				return 'text-green-500';
			case 'error':
				return 'text-red-500';
			default:
				return 'text-gray-500';
		}
	};
	
	const getStatusText = (status: string) => {
		switch (status) {
			case 'pending':
				return $i18n.t('Waiting');
			case 'processing':
				return $i18n.t('Processing');
			case 'transcribing':
				return $i18n.t('Transcribing');
			case 'completed':
				return $i18n.t('Completed');
			case 'error':
				return $i18n.t('Error');
			default:
				return $i18n.t('Unknown');
		}
	};
	
	const formatTime = (ms: number) => {
		const seconds = Math.floor(ms / 1000);
		const minutes = Math.floor(seconds / 60);
		const hours = Math.floor(minutes / 60);
		
		if (hours > 0) {
			return `${hours}h ${minutes % 60}m`;
		} else if (minutes > 0) {
			return `${minutes}m ${seconds % 60}s`;
		} else {
			return `${seconds}s`;
		}
	};
	
	const closeProgress = () => {
		progressStore.completeSession(sessionId);
	};
</script>

{#if session}
	<div class="fixed bottom-4 right-4 w-96 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-50">
		<div class="p-4">
			<!-- Header -->
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center space-x-2">
					<Spinner size="sm" />
					<h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">
						{$i18n.t('Processing Files')}
					</h3>
				</div>
				<button
					on:click={closeProgress}
					class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
				>
					<XMark size="sm" />
				</button>
			</div>
			
			<!-- Overall Progress -->
			<div class="mb-4">
				<div class="flex justify-between text-xs text-gray-600 dark:text-gray-400 mb-1">
					<span>{$i18n.t('Progress')}</span>
					<span>{session.processedFiles} / {session.totalFiles}</span>
				</div>
				<div class="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
					<div
						class="bg-blue-500 h-2 rounded-full transition-all duration-300"
						style="width: {(session.processedFiles / session.totalFiles) * 100}%"
					></div>
				</div>
			</div>
			
			<!-- Time Estimate -->
			{#if session.processedFiles > 0}
				{@const elapsed = Date.now() - session.startTime}
				{@const avgTimePerFile = elapsed / session.processedFiles}
				{@const remainingFiles = session.totalFiles - session.processedFiles}
				{@const estimatedTimeRemaining = avgTimePerFile * remainingFiles}
				
				<div class="text-xs text-gray-600 dark:text-gray-400 mb-4">
					<span>{$i18n.t('Estimated time remaining')}: {formatTime(estimatedTimeRemaining)}</span>
				</div>
			{/if}
			
			<!-- File List -->
			<div class="max-h-48 overflow-y-auto">
				{#each session.files as file}
					{@const StatusIcon = getStatusIcon(file.status)}
					
					<div class="flex items-center space-x-2 py-1">
						<StatusIcon size="xs" class={getStatusColor(file.status)} />
						<div class="flex-1 min-w-0">
							<div class="text-xs text-gray-900 dark:text-gray-100 truncate">
								{file.filename}
							</div>
							<div class="text-xs text-gray-500 dark:text-gray-400">
								{getStatusText(file.status)}
								{#if file.message}
									- {file.message}
								{/if}
								{#if file.progress > 0 && file.progress < 100}
									<span class="text-blue-500">({file.progress}%)</span>
								{/if}
							</div>
							{#if file.progress > 0 && file.progress < 100}
								<div class="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1 mt-1">
									<div
										class="bg-blue-500 h-1 rounded-full transition-all duration-300"
										style="width: {file.progress}%"
									></div>
								</div>
							{/if}
						</div>
						{#if file.status === 'processing' || file.status === 'transcribing'}
							<div class="w-4 h-4">
								<Spinner size="xs" />
							</div>
						{/if}
					</div>
				{/each}
			</div>
			
			<!-- Error Summary -->
			{#if session.files.some(f => f.status === 'error')}
				<div class="mt-3 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-xs">
					<div class="flex items-center space-x-1 text-red-600 dark:text-red-400">
						<XMark size="xs" />
						<span>{$i18n.t('Some files failed to process')}</span>
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if} 