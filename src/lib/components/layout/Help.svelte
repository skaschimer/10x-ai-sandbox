<script lang="ts">
	import { onMount, tick, getContext } from 'svelte';

	const i18n = getContext('i18n');

	import ShortcutsModal from '../chat/ShortcutsModal.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import HelpMenu from './Help/HelpMenu.svelte';

	let showShortcuts = false;
</script>

<div
	id="footer"
	class="fixed bottom-1.5 right-0 px-2 pt-2 z-20 flex lg:flex-row flex-col items-end"
>
	<div id="by-10x" class="lg:flex text-xs text-white-500">
		<a href="https://10x.gsa.gov" target="_blank" class="flex items-center">
			<span class="hidden lg:flex">Powered</span>&nbsp;
			<span class="lg:flex">by</span><span class="text-violet-600 lg:flex font-extrabold ms-1"
				>10x</span
			>
		</a>
	</div>
	<div id="help" class="hidden lg:flex ml-3">
		<button
			id="show-shortcuts-button"
			class="hidden"
			on:click={() => {
				showShortcuts = !showShortcuts;
			}}
		/>

		<HelpMenu
			showDocsHandler={() => {
				showShortcuts = !showShortcuts;
			}}
			showShortcutsHandler={() => {
				showShortcuts = !showShortcuts;
			}}
		>
			<Tooltip content={$i18n.t('Help')} placement="left">
				<button
					class="text-gray-600 dark:text-gray-300 bg-gray-300/20 size-5 flex items-center justify-center text-[0.7rem] rounded-full"
				>
					?
				</button>
			</Tooltip>
		</HelpMenu>
	</div>
</div>
<ShortcutsModal bind:show={showShortcuts} />
