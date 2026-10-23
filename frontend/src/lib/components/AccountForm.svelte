<script>
    import { enhance } from '$app/forms';
    import Button from './Button.svelte';
    import Field from './Field.svelte';
    import FormPage from './FormPage.svelte';

    let { title, subtitle, submit, color, account } = $props();
</script>

<FormPage {title} {subtitle}>
    <form method="POST" use:enhance>
        {#if account}
            <input type="hidden" name="user_id" value={account.user_id} />
        {/if}
        <Field label="ชื่อจริง" name="name" value={account?.name} placeholder="กรอกชื่อจริง" required />
        <Field label="นามสกุล" name="surname" value={account?.surname} placeholder="กรอกนามสกุล" required />
        <Field label="ชื่อผู้ใช้" name="username" value={account?.username} placeholder="กรอกชื่อผู้ใช้" required />
        <Field
            label="รหัสประจำตัวผู้ใช้"
            name="member_id"
            value={account?.member_id}
            placeholder="กรอกรหัสประจำตัวผู้ใช้"
            required
        />
        <Field
            label="รหัสผ่าน"
            name="password"
            type="password"
            placeholder={account
                ? 'กรอกรหัสผ่านอย่างน้อย 6 ตัว เว้นว่างหากไม่เปลี่ยน'
                : 'กรอกรหัสผ่าน (อย่างน้อย 6 ตัวอักษร)'}
            required={!account}
        />
        <label class="block mb-6">
            <span class="block text-sm text-gray-800 mb-2">บทบาท</span>
            <select
                name="role"
                value={account?.role}
                required
                class="w-full bg-white border rounded-xl px-4 py-3 text-sm text-gray-800 appearance-none"
            >
                {#each ['student', 'instructor', 'admin'] as role (role)}
                    <option value={role}>{role}</option>
                {/each}
            </select>
        </label>
        <Button {color} class="w-full">{submit}</Button>
    </form>
</FormPage>
