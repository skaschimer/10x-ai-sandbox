<script>
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import AccessControl from './AccessControl.svelte';

	export let show = false;
	export let accessControl = null;

	export let onChange = () => {};

	let headingId = 'access-control-heading';
</script>

<Modal size="sm" {headingId} bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-3 pb-1">
			<h2 class=" text-lg font-medium self-center font-primary" id={headingId}>
				{$i18n.t('Access Control')}
			</h2>
		</div>

		<div class="w-full px-5 pb-4 dark:text-white">
			<AccessControl bind:accessControl {onChange} />
		</div>
	</div>
</Modal>
