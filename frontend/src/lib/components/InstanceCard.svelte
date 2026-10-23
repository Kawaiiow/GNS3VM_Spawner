<script>
    import { enhance } from '$app/forms';
    import { refreshAll } from '$app/navigation';
    import { confirmed } from '#lib/confirm.js';
    import Button from './Button.svelte';

    let { title, description, nameLabel, instance, creatable = false, timed = false } = $props();
    let visible = $state(false);

    const ready = $derived(instance && ['running', 'stopped'].includes(instance.state));
    const running = $derived(instance?.state === 'running');
    const pending = $derived(instance && (!ready || (running && !instance.public_ip)));

    $effect(() => {
        if (!pending) return;
        const timer = setInterval(refreshAll, 3000);
        return () => clearInterval(timer);
    });

    function formatExpires(timestamp) {
        const date = new Date(timestamp * 1000);
        const time = date.toLocaleTimeString('en-GB', { timeZone: 'Asia/Bangkok', hourCycle: 'h23' });
        return `${time} - ${date.toLocaleDateString('th-TH', { timeZone: 'Asia/Bangkok' })}`;
    }

    async function copy(event) {
        const input = event.currentTarget;
        await navigator.clipboard.writeText(input.value);
        input.blur();
    }
</script>

{#snippet field(label, value)}
    <p class="text-gray-600 text-sm">{label}</p>
    <p class="text-gray-800 text-lg">{value}</p>
{/snippet}

<div class="rounded-lg border shadow-xs p-6 flex flex-col">
    <div class="flex items-center justify-between">
        <div>
            <p class="text-gray-800 text-lg">{title}</p>
            <p class="text-gray-600 text-sm">{description}</p>
        </div>
        {#if !instance}
            {#if creatable}
                <form method="POST" action="?/create" use:enhance>
                    <Button color="emerald">เพิ่ม</Button>
                </form>
            {/if}
        {:else if !ready}
            <Button disabled>รอสักครู่</Button>
        {:else}
            <form
                method="POST"
                action="?/delete"
                use:enhance={confirmed(`ต้องการลบเครื่องของ ${title} ใช่หรือไม่`)}
            >
                <input type="hidden" name="instance_id" value={instance.instance_id} />
                <Button color="rose">ลบ</Button>
            </form>
        {/if}
    </div>
    {#if ready}
        <div class="text-gray-600 text-sm my-4">
            <hr class="mb-4" />
            {#if timed && instance.expires_at}
                {@render field('หมดเวลาเมื่อ', formatExpires(instance.expires_at))}
            {/if}
            {@render field(nameLabel, instance.name)}
            {@render field('สถานะ', instance.state)}
            {#if instance.public_ip}
                {@const url = `http://${instance.public_ip}:3080`}
                {@render field('Public IP', instance.public_ip)}
                {@render field('พอร์ต', '3080')}
                <p class="text-gray-600 text-sm">URL</p>
                <p class="text-gray-800 text-lg"><a href={url} target="_blank" rel="noreferrer">{url}</a></p>
                {@render field('ชื่อผู้ใช้ GNS3', instance.gns3_user)}
                <p class="text-gray-600 text-sm">รหัสผ่าน GNS3</p>
                <div class="relative">
                    <input
                        type={visible ? 'text' : 'password'}
                        value={instance.gns3_password}
                        aria-label="รหัสผ่าน GNS3"
                        title="คลิกเพื่อคัดลอกรหัสผ่าน"
                        onclick={copy}
                        readonly
                        class="w-full bg-transparent text-gray-800 text-lg pr-8 outline-none cursor-pointer"
                    />
                    <button
                        type="button"
                        aria-label="แสดงรหัสผ่าน"
                        onclick={() => (visible = !visible)}
                        class="absolute inset-y-0 right-0 flex items-center"
                    >
                        <img src={visible ? '/image/eye_close.svg' : '/image/eye_open.svg'} alt="" class="h-5 w-auto" />
                    </button>
                </div>
            {/if}
        </div>
        <div class="flex gap-2 mt-auto">
            <form method="POST" action={running ? '?/stop' : '?/start'} use:enhance class="w-full">
                <input type="hidden" name="instance_id" value={instance.instance_id} />
                <Button color={running ? 'orange' : 'emerald'} class="w-full">{running ? 'หยุด' : 'เริ่ม'}</Button>
            </form>
            {#if timed && running && instance.remaining_seconds != null}
                <form method="POST" action="?/extend" use:enhance class="w-full">
                    <input type="hidden" name="instance_id" value={instance.instance_id} />
                    <Button color="sky" class="w-full">รีเซ็ตเวลา</Button>
                </form>
            {/if}
        </div>
    {/if}
</div>
