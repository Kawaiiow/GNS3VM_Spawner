<script>
    import { afterNavigate } from '$app/navigation';

    let { signedIn, username } = $props();
    let open = $state(false);

    afterNavigate(() => (open = false));
</script>

<div class="bg-white border-b fixed top-0 w-full">
    <div class="flex justify-between max-w-7xl mx-auto px-6 py-3">
        <a href="/" class="flex items-center">
            <img src="/image/netlab_logo.png" alt="NetLab" class="inline-block h-10 w-auto" />
        </a>
        {#if signedIn}
            <div class="relative">
                <button
                    onclick={() => (open = !open)}
                    class="flex items-center justify-center w-10 h-10 rounded-full bg-gray-800 hover:bg-gray-900 transition-colors duration-200 ease-in-out text-white text-xs"
                >
                    {username?.[0].toUpperCase() ?? '?'}
                </button>
                {#if open}
                    <div class="absolute right-0 top-full mt-6 w-48 bg-white border rounded-lg shadow-xs p-2">
                        <a
                            href="/profile"
                            class="block w-full px-4 py-2 text-gray-800 hover:text-gray-900 transition-colors duration-200 ease-in-out text-sm"
                        >
                            โปรไฟล์
                        </a>
                        <hr class="my-2" />
                        <form
                            method="POST"
                            action="/signout"
                            onsubmit={(e) => confirm('ต้องการออกจากระบบใช่หรือไม่') || e.preventDefault()}
                        >
                            <button
                                class="block w-full px-4 py-2 text-rose-600 hover:text-rose-700 transition-colors duration-200 ease-in-out text-left text-sm"
                            >
                                ออกจากระบบ
                            </button>
                        </form>
                    </div>
                {/if}
            </div>
        {:else}
            <a
                href="/signin"
                class="px-4 py-3 bg-gray-800 hover:bg-gray-900 transition-colors duration-200 ease-in-out text-white text-xs rounded-xl"
            >
                ลงชื่อเข้าใช้
            </a>
        {/if}
    </div>
</div>
