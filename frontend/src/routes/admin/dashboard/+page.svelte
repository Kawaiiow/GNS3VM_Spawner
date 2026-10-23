<script>
    import { enhance } from '$app/forms';
    import { confirmed } from '#lib/confirm.js';
    import Button from '#lib/components/Button.svelte';

    let { data } = $props();

    const badges = {
        running: ['bg-green-600', 'ใช้งานอยู่'],
        stopped: ['bg-yellow-600', 'หยุดใช้งาน']
    };
</script>

{#snippet status(instance)}
    {@const [color, label] = badges[instance?.state] ?? ['bg-red-600', 'ไม่ได้ใช้งาน']}
    <span class="whitespace-nowrap text-xs px-3 py-1.5 rounded-full text-white {color}">{label}</span>
{/snippet}

<svelte:head>
    <title>แดชบอร์ด - NetLab</title>
</svelte:head>

<div class="max-w-6xl min-h-screen mx-auto px-6 py-28">
    <p class="text-gray-800 text-4xl">ยินดีต้อนรับ, {data.username}</p>
    <p class="text-gray-600 text-xl mb-12">ภาพรวมและการจัดการระบบทั้งหมดอยู่ในมือคุณ</p>
    <div class="flex items-center justify-between mb-4">
        <div>
            <p class="text-gray-800 text-2xl">รายชื่อบัญชีทั้งหมด</p>
            <p class="text-gray-600 text-base">เพิ่ม แก้ไข และลบบัญชีของผู้ใช้แต่ละคนในระบบ</p>
        </div>
        <Button href="/admin/account/create">เพิ่มบัญชี</Button>
    </div>
    <div class="bg-white border rounded-lg overflow-x-auto shadow-xs">
        <table class="min-w-lg w-full">
            <thead>
                <tr class="text-xs text-gray-600 tracking-wide">
                    <th class="px-4 py-3 text-left">รหัสประจำตัวผู้ใช้</th>
                    <th class="px-4 py-3 text-center">ชื่อผู้ใช้</th>
                    <th class="px-4 py-3 text-center">บทบาท</th>
                    <th class="px-4 py-3 text-center">สถานะ Sandbox</th>
                    <th class="px-4 py-3 text-center whitespace-nowrap">ที่อยู่ IP Sandbox</th>
                    <th class="px-4 py-3 text-center">สถานะแบบฝึกหัด</th>
                    <th class="px-4 py-3 text-center whitespace-nowrap">ที่อยู่ IP แบบฝึกหัด</th>
                    <th class="px-4 py-3 text-right">การจัดการ</th>
                </tr>
            </thead>
            <tbody>
                {#each data.users as user (user.user_id)}
                    {@const sandbox = user.instances.find((instance) => instance.kind === 'sandbox')}
                    {@const exercise = user.instances.find((instance) => instance.kind === 'exercise')}
                    <tr class="border-t">
                        <td class="px-4 py-3 text-left text-gray-800">{user.member_id}</td>
                        <td class="px-4 py-3 text-center text-gray-800">{user.username}</td>
                        <td class="px-4 py-3 text-center text-gray-800">{user.role}</td>
                        {#each [sandbox, exercise] as instance}
                            <td class="px-4 py-3 text-center">{@render status(instance)}</td>
                            <td class="px-4 py-3 text-center text-gray-800">{instance?.public_ip || '-'}</td>
                        {/each}
                        <td class="px-4 py-3 text-right">
                            <div class="flex justify-end gap-2">
                                {#if user.username === data.username}
                                    <Button size="sm" disabled>แก้ไข</Button>
                                    <Button size="sm" disabled>ลบ</Button>
                                {:else}
                                    <Button size="sm" href="/admin/account/update?user_id={user.user_id}">แก้ไข</Button>
                                    <form method="POST" action="?/delete" use:enhance={confirmed('ต้องการลบบัญชีนี้ใช่หรือไม่')}>
                                        <input type="hidden" name="user_id" value={user.user_id} />
                                        <Button size="sm" color="rose">ลบ</Button>
                                    </form>
                                {/if}
                            </div>
                        </td>
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>
</div>
