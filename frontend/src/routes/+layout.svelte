<script>
    import '../app.css';
    import { page } from '$app/state';
    import Footer from '#lib/components/Footer.svelte';
    import Navbar from '#lib/components/Navbar.svelte';

    let { data, children } = $props();

    $effect(() => {
        if (page.form?.message) alert(page.form.message);
    });
</script>

<Navbar signedIn={data.signedIn} username={data.username} />
{@render children()}
<Footer />
