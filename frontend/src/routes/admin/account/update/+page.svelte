<script>
    import AccountForm from '#lib/components/AccountForm.svelte';

    let { data } = $props();
</script>

<svelte:head>
    <title>แก้ไขบัญชี - NetLab</title>
</svelte:head>

<AccountForm title="แก้ไขบัญชี" subtitle="แก้ไขบัญชีใน NetLab" submit="แก้ไข" color="sky" account={data.account} />
