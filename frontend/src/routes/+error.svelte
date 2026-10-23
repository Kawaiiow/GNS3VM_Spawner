<script>
    import { page } from '$app/state';

    const views = {
        404: {
            gif: 'python',
            color: 'text-yellow-500',
            title: 'ไม่พบหน้านี้',
            subtitle: "This is not the page you're looking for",
            quote: 'Page not found, but never stop trying.'
        },
        503: {
            gif: 'cobra',
            color: 'text-red-500',
            title: 'ไม่พร้อมใช้งาน',
            subtitle: 'No server is currently available to service your request',
            quote: 'Service unavailable, but never stop trying.'
        }
    };

    const view = $derived(views[page.status] ?? views[503]);
</script>

<svelte:head>
    <title>{view.title} - NetLab</title>
</svelte:head>

<div class="flex justify-center items-center min-h-screen w-full">
    <div class="text-center max-w-7xl p-6">
        <img src="/animation/{view.gif}.gif" alt="" class="inline-block h-40 mx-auto mb-4" />
        <p class="text-6xl mb-1 {view.color}">{view.title}</p>
        <p class="text-sm text-gray-600 mb-8">{view.subtitle}</p>
        <p class="text-gray-600 text-base mb-10">"{view.quote}" - Sarin</p>
    </div>
</div>
