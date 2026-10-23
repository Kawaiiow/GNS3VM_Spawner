<script>
    let {
        color = 'gray',
        size = 'md',
        href,
        disabled = false,
        class: className = '',
        children,
        ...rest
    } = $props();

    const colors = {
        gray: 'bg-gray-800 hover:bg-gray-900',
        emerald: 'bg-emerald-600 hover:bg-emerald-700',
        rose: 'bg-rose-600 hover:bg-rose-700',
        orange: 'bg-orange-600 hover:bg-orange-700',
        sky: 'bg-sky-600 hover:bg-sky-700'
    };
    const sizes = {
        md: 'px-4 py-3 text-sm',
        sm: 'px-3 py-2 text-xs'
    };

    const classes = $derived(
        [
            'rounded-xl transition-colors duration-200 ease-in-out',
            sizes[size],
            disabled ? 'bg-gray-600 text-gray-200' : `${colors[color]} text-white`,
            className
        ].join(' ')
    );
</script>

{#if href && !disabled}
    <a {href} class={classes} {...rest}>{@render children()}</a>
{:else}
    <button {disabled} class={classes} {...rest}>{@render children()}</button>
{/if}
