<script>
    let { title, subtitle, children } = $props();
</script>

<div class="max-w-md mx-auto min-h-screen px-6 py-28">
    <div class="text-center">
        <img src="/image/netlab_icon.png" alt="NetLab" class="inline-block max-h-24 w-auto mb-6" />
        <p class="text-2xl text-gray-800">{title}</p>
        <p class="text-base text-gray-600 mb-6">{subtitle}</p>
    </div>
    {@render children()}
</div>
