<script>
    import { enhance } from '$app/forms';
    import Button from '#lib/components/Button.svelte';
    import Field from '#lib/components/Field.svelte';
    import FormPage from '#lib/components/FormPage.svelte';
</script>

<svelte:head>
    <title>ลงชื่อเข้าใช้ - NetLab</title>
</svelte:head>

<FormPage title="ยินดีต้อนรับ, NetLabber!" subtitle="ลงชื่อเข้าใช้เพื่อเข้าถึง NetLab">
    <form method="POST" use:enhance>
        <Field label="ชื่อผู้ใช้" name="identifier" placeholder="กรอกชื่อผู้ใช้ของคุณ" required />
        <Field label="รหัสผ่าน" name="password" type="password" placeholder="กรอกรหัสผ่านของคุณ" required />
        <p class="text-right text-sm text-gray-800 mb-4">ลืมรหัสผ่าน? ช่วยไม่ได้</p>
        <Button class="w-full">ลงชื่อเข้าใช้</Button>
    </form>
</FormPage>
