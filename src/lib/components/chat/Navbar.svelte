<script lang="ts">
	import { getContext, tick } from 'svelte';
	import { config } from '$lib/stores';
	import { toast } from 'svelte-sonner';

	import {
		WEBUI_NAME,
		chatId,
		mobile,
		settings,
		showArchivedChats,
		showControls,
		showSidebar,
		temporaryChatEnabled,
		user
	} from '$lib/stores';

	import { slide } from 'svelte/transition';
	import { page } from '$app/stores';

	import ShareChatModal from '../chat/ShareChatModal.svelte';
	import ModelSelector from '../chat/ModelSelector.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Menu from '$lib/components/layout/Navbar/Menu.svelte';
	import UserMenu from '$lib/components/layout/Sidebar/UserMenu.svelte';
	import MenuLines from '../icons/MenuLines.svelte';
	import AdjustmentsHorizontal from '../icons/AdjustmentsHorizontal.svelte';
	import NewChatIcon from '../icons/NewChatIcon.svelte';
	import Help from '$lib/components/layout/Help.svelte';

	const i18n = getContext('i18n');

	export let initNewChat: Function;
	export let title: string = $WEBUI_NAME;
	export let shareEnabled: boolean = false;

	export let chat;
	export let selectedModels;
	export let showModelSelector = true;

	let showShareChatModal = false;
	let showDownloadChatModal = false;

	async function focusFirstChatItem() {
		// Wait for the DOM to update before focusing the first chat item
		await tick();

		const firstChatItem = document.getElementById('sidebar-open-toggle-button');
		if (firstChatItem) {
			firstChatItem.focus();
		}
	}
</script>

<ShareChatModal bind:show={showShareChatModal} chatId={$chatId} />

<div class="sticky top-0 z-30">
	<div class="w-full px-1.5 py-1.5 -mb-8 flex items-center">
		<div
			class=" bg-gradient-to-b via-50% from-white via-white to-transparent dark:from-gray-900 dark:via-gray-900 dark:to-transparent pointer-events-none absolute inset-0 -bottom-7 z-[-1] blur"
		></div>

		<div class=" flex max-w-full w-full mx-auto px-1 pt-0.5 bg-transparent">
			<div class="flex items-center w-full max-w-full">
				<div
					class="{$showSidebar
						? 'md:hidden'
						: ''} mr-1 self-start flex flex-none items-center text-gray-600 dark:text-gray-400"
				>
					<button
						id="sidebar-toggle-button"
						class="cursor-pointer px-2 py-2 flex rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
						on:click={() => {
							showSidebar.set(!$showSidebar);

							// Focus the first chat item when the sidebar is opened.
							focusFirstChatItem();
						}}
						aria-expanded={$showSidebar}
						aria-label="Toggle Sidebar"
					>
						<div class=" m-auto self-center">
							<MenuLines />
						</div>
					</button>
				</div>

				{#if !$mobile}
					<Tooltip content={$i18n.t('New Chat')}>
						<button
							id="new-chat-button"
							class="ml-2 mr-4 {$showSidebar ? 'md:hidden' : ''}"
							aria-label="New Chat"
							on:click={() => {
								initNewChat();
							}}
						>
							<NewChatIcon strokeWidth="2" />
						</button>
					</Tooltip>
				{/if}

				<div
					class="flex-1 overflow-hidden max-w-full py-0.5
				{$showSidebar ? 'ml-1' : ''}
				"
				>
					{#if showModelSelector}
						<ModelSelector bind:selectedModels showSetDefault={!shareEnabled} />
					{/if}
				</div>

				<div class="self-start flex flex-none items-center text-gray-600 dark:text-gray-400">
					<div class="px-3 py-1 bg-gray-800 text-white text-sm rounded-full">{$i18n.t('BETA')}</div>
					<Help />
					<!-- <div class="md:hidden flex self-center w-[1px] h-5 mx-2 bg-gray-300 dark:bg-stone-700" /> -->
					{#if shareEnabled && chat && (chat.id || $temporaryChatEnabled)}
						<Menu
							{chat}
							{shareEnabled}
							shareHandler={() => {
								showShareChatModal = !showShareChatModal;
							}}
							downloadHandler={() => {
								showDownloadChatModal = !showDownloadChatModal;
							}}
						>
							<button
								class="flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								id="chat-context-menu-button"
							>
								<div class=" m-auto self-center">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="size-5"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M6.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM18.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
										/>
									</svg>
								</div>
							</button>
						</Menu>
					{:else if $mobile && $config?.features?.enable_chat_controls}
						<Tooltip content={$i18n.t('Controls')}>
							<button
								class=" flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								on:click={async () => {
									await showControls.set(!$showControls);
								}}
								aria-label="Controls"
							>
								<div class=" m-auto self-center">
									<AdjustmentsHorizontal className=" size-5" strokeWidth="0.5" />
								</div>
							</button>
						</Tooltip>
					{/if}

					{#if !$mobile && $config?.features?.enable_chat_controls}
						<Tooltip content={$i18n.t('Controls')}>
							<button
								class=" flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								on:click={async () => {
									await showControls.set(!$showControls);
								}}
								aria-label="Controls"
							>
								<div class=" m-auto self-center">
									<AdjustmentsHorizontal className=" size-5" strokeWidth="0.5" />
								</div>
							</button>
						</Tooltip>
					{/if}

					{#if $mobile}
						<Tooltip content={$i18n.t('New Chat')}>
							<button
								id="new-chat-button"
								class=" flex {$showSidebar
									? 'md:hidden'
									: ''} cursor-pointer px-2 py-2 rounded-xl text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								on:click={() => {
									initNewChat();
								}}
								aria-label="New Chat"
							>
								<div class=" m-auto self-center">
									<NewChatIcon strokeWidth="2" />
								</div>
							</button>
						</Tooltip>
					{/if}

					{#if $user !== undefined}
						<UserMenu
							className="max-w-[200px]"
							role={$user.role}
							on:show={(e) => {
								if (e.detail === 'archived-chat') {
									showArchivedChats.set(true);
								}
							}}
						>
							<button
								class="select-none flex rounded-xl p-1.5 w-full hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								aria-label="User Menu"
							>
								<div class=" self-center">
									<img
										src={$user.profile_image_url}
										class="size-6 object-cover rounded-full"
										alt="User profile"
										draggable="false"
									/>
								</div>
							</button>
						</UserMenu>
					{/if}
				</div>
			</div>
		</div>
	</div>
</div>
