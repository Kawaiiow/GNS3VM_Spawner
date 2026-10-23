<script>
    import { enhance } from '$app/forms';
    import Button from '#lib/components/Button.svelte';
    import Field from '#lib/components/Field.svelte';
    import FormPage from '#lib/components/FormPage.svelte';

    let { data } = $props();
</script>

<svelte:head>
    <title>เพิ่มแบบฝึกหัด - NetLab</title>
</svelte:head>

<FormPage title="เพิ่มแบบฝึกหัด" subtitle="เพิ่มแบบฝึกหัดใน NetLab">
    <form method="POST" use:enhance>
        <input type="hidden" name="instance_id" value={data.instanceId} />
        <Field label="หัวข้อ" name="title" placeholder="กรอกหัวข้อ" required />
        <Field label="คำอธิบาย" name="description" placeholder="กรอกคำอธิบาย" required />
        <div class="mb-6">
            <p class="block text-sm text-gray-800 mb-2">โจทย์</p>
            {#if data.projects.length}
                <div class="flex flex-col gap-2">
                    {#each data.projects as project (project.project_id)}
                        <label class="flex items-center justify-between gap-2 text-sm text-gray-600 cursor-pointer">
                            <span class="flex items-center gap-2">
                                <input type="checkbox" name="project_ids" value={project.project_id} checked />
                                <span>{project.name}</span>
                            </span>
                            <span class="text-xs text-gray-600">{project.status}</span>
                        </label>
                    {/each}
                </div>
            {:else}
                <p class="text-sm text-gray-600">ไม่พบโจทย์ใน GNS3</p>
            {/if}
        </div>
        <Button color="emerald" disabled={!data.projects.length} class="w-full">เพิ่ม</Button>
    </form>
</FormPage>
