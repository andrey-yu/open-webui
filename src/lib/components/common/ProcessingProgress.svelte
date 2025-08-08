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

    // Derived UI subset: latest completed, current, and next two pending
    let currentFile: any = undefined;
    let latestCompleted: any = null;
    let pendingToShow: any[] = [];
    let totalShown = 0;
    let remaining = 0;
	
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

    // Compute the limited list to display
    $: {
        if (session && session.files && session.files.length > 0) {
            currentFile = session.files.find(f => f.status === 'processing' || f.status === 'transcribing');
            const completedList = session.files.filter(f => f.status === 'completed');
            latestCompleted = completedList.length > 0 ? completedList[completedList.length - 1] : null;
            const pendingCandidates = session.files.filter(f => f.status === 'pending');
            pendingToShow = pendingCandidates.slice(0, 2);
        } else {
            currentFile = undefined;
            latestCompleted = null;
            pendingToShow = [];
        }

        totalShown = (latestCompleted ? 1 : 0) + (currentFile ? 1 : 0) + (pendingToShow ? pendingToShow.length : 0);
        remaining = Math.max((session ? session.totalFiles : 0) - totalShown, 0);
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
			
            <!-- File List (limited: 1 completed, 1 current, 2 pending) -->
            <div class="max-h-48 overflow-y-auto">
                {#if session.files && session.files.length > 0}
                    {#key session.currentProcessingFileIndex}
                        {#if latestCompleted}
                            {@const CompletedIcon = getStatusIcon(latestCompleted.status)}
                            <div class="flex items-center space-x-2 py-1">
                                <CompletedIcon size="xs" class={getStatusColor(latestCompleted.status)} />
                                <div class="flex-1 min-w-0">
                                    <div class="text-xs text-gray-900 dark:text-gray-100 truncate">
                                        {latestCompleted.filename}
                                    </div>
                                    <div class="text-xs text-green-600 dark:text-green-400">
                                        {getStatusText(latestCompleted.status)}
                                    </div>
                                </div>
                            </div>
                        {/if}

                        {#if currentFile}
                            {@const CurrentIcon = getStatusIcon(currentFile.status)}
                            <div class="flex items-center space-x-2 py-1">
                                <CurrentIcon size="xs" class={getStatusColor(currentFile.status)} />
                                <div class="flex-1 min-w-0">
                                    <div class="text-xs text-gray-900 dark:text-gray-100 truncate">
                                        {currentFile.filename}
                                    </div>
                                    <div class="text-xs text-blue-600 dark:text-blue-400">
                                        {getStatusText(currentFile.status)}
                                        {#if currentFile.message}
                                            - {currentFile.message}
                                        {/if}
                                        {#if currentFile.progress > 0 && currentFile.progress < 100}
                                            <span class="text-blue-500">({currentFile.progress}%)</span>
                                        {/if}
                                    </div>
                                    {#if currentFile.progress > 0 && currentFile.progress < 100}
                                        <div class="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1 mt-1">
                                            <div class="bg-blue-500 h-1 rounded-full transition-all duration-300" style="width: {currentFile.progress}%"></div>
                                        </div>
                                    {/if}
                                </div>
                                <div class="w-4 h-4">
                                    <Spinner size="xs" />
                                </div>
                            </div>
                        {/if}

                        {#each pendingToShow as file}
                            {@const PendingIcon = getStatusIcon(file.status)}
                            <div class="flex items-center space-x-2 py-1">
                                <PendingIcon size="xs" class={getStatusColor(file.status)} />
                                <div class="flex-1 min-w-0">
                                    <div class="text-xs text-gray-900 dark:text-gray-100 truncate">
                                        {file.filename}
                                    </div>
                                    <div class="text-xs text-gray-600 dark:text-gray-400">
                                        {getStatusText(file.status)}
                                    </div>
                                </div>
                            </div>
                        {/each}

                        {#if remaining > 0}
                            <div class="text-[11px] text-gray-500 dark:text-gray-400 py-1 pl-6">+{remaining} more</div>
                        {/if}
                    {/key}
                {/if}
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