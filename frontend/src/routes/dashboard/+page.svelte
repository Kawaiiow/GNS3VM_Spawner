<script>
    import ExerciseTable from '#lib/components/ExerciseTable.svelte';
    import InstanceCard from '#lib/components/InstanceCard.svelte';

    let { data } = $props();
    const sandbox = $derived(data.instances.find((instance) => !instance.exercise_id));
    const exercise = $derived(data.instances.find((instance) => instance.exercise_id));
</script>

<svelte:head>
    <title>แดชบอร์ด - NetLab</title>
</svelte:head>

<div class="max-w-6xl min-h-screen mx-auto px-6 py-28">
    <p class="text-gray-800 text-4xl">ยินดีต้อนรับ, {data.username}</p>
    <p class="text-gray-600 text-xl mb-12">เริ่มต้นทำแล็บหรือแบบฝึกหัดเพื่อพัฒนาศักยภาพ</p>
    <p class="text-gray-800 text-2xl">เครื่องของฉัน</p>
    <p class="text-gray-600 text-base mb-4">ทดลองในเครื่อง Sandbox หรือใช้เครื่องที่เตรียมไว้ให้ตามแบบฝึกหัด</p>
    <div class="grid gap-6 md:grid-cols-2 mb-12">
        <InstanceCard
            title="Sandbox"
            description="เครื่องเปล่าสำหรับทดลองด้วยตัวเอง"
            nameLabel="ชื่อ Sandbox"
            instance={sandbox}
            creatable
            timed
        />
        <InstanceCard
            title="แบบฝึกหัด"
            description="เครื่องที่เตรียมโจทย์ไว้ให้"
            nameLabel="ชื่อแบบฝึกหัด"
            instance={exercise}
            timed
        />
    </div>
    <p class="text-gray-800 text-2xl">แบบฝึกหัดที่เปิดให้ทำ</p>
    <p class="text-gray-600 text-base mb-4">เลือกแบบฝึกหัดเพื่อสร้างเครื่องพร้อมแบบฝึกหัดนั้น</p>
    <ExerciseTable exercises={data.exercises} busy={!!exercise} />
</div>
