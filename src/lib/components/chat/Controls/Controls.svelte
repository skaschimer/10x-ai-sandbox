<script lang="ts">
	import { createEventDispatcher, getContext, onMount, tick } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import XMark from '$lib/components/icons/XMark.svelte';
	import AdvancedParams from '../Settings/Advanced/AdvancedParams.svelte';
	import Valves from '$lib/components/chat/Controls/Valves.svelte';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import Collapsible from '$lib/components/common/Collapsible.svelte';

	import { user } from '$lib/stores';
	export let models = [];
	export let chatFiles = [];
	export let params = {};

	let showValves = false;

	// This code is to move the focus to the first focusable element when the component when it becomes visible.
	export let visible = false;
	let firstFocusable;

	// React to visibility changes
	$: if (visible) {
		(async () => {
			await tick();
			if (firstFocusable) {
				firstFocusable.focus();
			}
		})();
	}
</script>

<div class=" dark:text-white">
	<div class=" flex items-center justify-between dark:text-gray-100 mb-2">
		<div class=" text-lg font-medium self-center font-primary">{$i18n.t('Chat Controls')}</div>
		<button
			id="close-button"
			class="self-center"
			on:click={() => {
				dispatch('close');
			}}
			bind:this={firstFocusable}
		>
			<XMark className="size-3.5" />
		</button>
	</div>

	<div class=" dark:text-gray-200 text-sm font-primary py-0.5 px-0.5">
		{#if chatFiles.length > 0}
			<Collapsible title={$i18n.t('Files')} open={true} buttonClassName="w-full">
				<div class="flex flex-col gap-1 mt-1.5" slot="content">
					{#each chatFiles as file, fileIdx}
						<FileItem
							className="w-full"
							item={file}
							edit={true}
							url={file?.url ? file.url : null}
							name={file.name}
							type={file.type}
							size={file?.size}
							dismissible={true}
							on:dismiss={() => {
								// Remove the file from the chatFiles array

								chatFiles.splice(fileIdx, 1);
								chatFiles = chatFiles;
							}}
							on:click={() => {
								console.log(file);
							}}
						/>
					{/each}
				</div>
			</Collapsible>

			<hr class="my-2 border-gray-50 dark:border-gray-700/10" />
		{/if}

		<Collapsible bind:open={showValves} title={$i18n.t('Valves')} buttonClassName="w-full">
			<div class="text-sm" slot="content">
				<Valves show={showValves} />
			</div>
		</Collapsible>

		<hr class="my-2 border-gray-50 dark:border-gray-700/10" />

		<Collapsible title={$i18n.t('System Prompt')} open={true} buttonClassName="w-full">
			<div class="mt-0.5" slot="content">
				<textarea
					bind:value={params.system}
					class="w-full rounded-lg py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-850 border border-gray-400 resize-none"
					rows="4"
					placeholder={$i18n.t('Enter system prompt')}
				/>
			</div>
		</Collapsible>

		<hr class="my-2 border-gray-50 dark:border-gray-700/10" />

		<Collapsible title={$i18n.t('Advanced Params')} open={true} buttonClassName="w-full">
			<div class="text-sm mt-1.5" slot="content">
				<div>
					<AdvancedParams admin={$user?.role === 'admin'} bind:params />
				</div>
			</div>
		</Collapsible>
	</div>
</div>
