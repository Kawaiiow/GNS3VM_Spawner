<script>
    let { data } = $props();
    const user = $derived(data.user);

    const stats = $derived([
        [user.active_instance_id ? 1 : 0, 'Sandbox ที่ทำอยู่'],
        [user.active_exercise_instance_id ? 1 : 0, 'แบบฝึกหัดที่ทำอยู่']
    ]);
    const details = $derived([
        ['ชื่อผู้ใช้', user.username],
        ['รหัสประจำตัวผู้ใช้', user.member_id],
        ['ชื่อจริง-นามสกุล', user.full_name],
        ['บทบาท', user.role],
        ['เข้าใช้งานตั้งแต่', user.created_at.slice(0, 10)],
        ['เข้าใช้งานล่าสุด', user.updated_at.slice(0, 10)]
    ]);
</script>

<svelte:head>
    <title>โปรไฟล์ - NetLab</title>
</svelte:head>

<div class="max-w-md mx-auto min-h-screen px-6 py-28">
    <div class="flex flex-col items-center text-center mb-8">
        <div class="flex items-center justify-center w-24 h-24 rounded-full bg-gray-800 text-white text-4xl mb-4">
            {user.username[0].toUpperCase()}
        </div>
        <p class="text-2xl text-gray-800">{user.full_name}</p>
        <p class="text-base text-gray-600 mb-2">@{user.username}</p>
        <span class="inline-flex items-center rounded-full bg-gray-800 px-3 py-1 text-sm text-white">{user.role}</span>
    </div>
    <div class="grid grid-cols-2 gap-6 mb-8">
        {#each stats as [count, label] (label)}
            <div class="rounded-lg border shadow-xs px-3 py-6 text-center">
                <p class="text-4xl text-gray-800">{count}</p>
                <p class="text-sm text-gray-600">{label}</p>
            </div>
        {/each}
    </div>
    <div class="divide-y border-y">
        {#each details as [label, value] (label)}
            <div class="flex items-center justify-between py-4">
                <p class="text-sm text-gray-600">{label}</p>
                <p class="text-gray-800">{value}</p>
            </div>
        {/each}
    </div>
</div>
