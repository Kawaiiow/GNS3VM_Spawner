<script>
    let { label, type = 'text', ...rest } = $props();
    let visible = $state(false);
</script>

<label class="block mb-4">
    <span class="block text-sm text-gray-800 mb-2">{label}</span>
    <span class="relative block">
        <input
            type={visible ? 'text' : type}
            class="w-full bg-white border rounded-xl px-4 py-3 text-sm text-gray-800 placeholder:text-gray-600"
            {...rest}
        />
        {#if type === 'password'}
            <button
                type="button"
                aria-label="แสดงรหัสผ่าน"
                onclick={() => (visible = !visible)}
                class="absolute inset-y-0 right-0 flex items-center pr-3"
            >
                <img src={visible ? '/image/eye_close.svg' : '/image/eye_open.svg'} alt="" class="h-5 w-auto" />
            </button>
        {/if}
    </span>
</label>
