<script>
    import { enhance } from '$app/forms';
    import { confirmed } from '#lib/confirm.js';
    import Button from './Button.svelte';

    let { exercises, busy, deletable = false } = $props();
</script>

<div class="bg-white border rounded-lg overflow-x-auto shadow-xs">
    <table class="min-w-lg w-full">
        <thead>
            <tr class="text-xs text-gray-600 tracking-wide">
                <th class="px-4 py-3 text-left">หัวข้อ</th>
                <th class="px-4 py-3 text-left">คำอธิบาย</th>
                <th class="px-4 py-3 text-center">สถานะ</th>
                <th class="px-4 py-3 text-right">การจัดการ</th>
            </tr>
        </thead>
        <tbody>
            {#each exercises as exercise (exercise.exercise_id)}
                {@const open = exercise.status === 'available'}
                <tr class="border-t">
                    <td class="px-4 py-3 text-left text-gray-800 whitespace-nowrap">{exercise.title}</td>
                    <td class="px-4 py-3 text-left text-gray-800 whitespace-nowrap">{exercise.description}</td>
                    <td class="text-center whitespace-nowrap">
                        <span class="text-xs px-3 py-1.5 rounded-full text-white {open ? 'bg-green-600' : 'bg-red-600'}">
                            {open ? 'เปิดอยู่' : 'ปิดอยู่'}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-right">
                        <div class="flex justify-end gap-2">
                            <form method="POST" action="?/create" use:enhance>
                                <input type="hidden" name="exercise_id" value={exercise.exercise_id} />
                                <Button size="sm" color="emerald" disabled={busy || exercise.status === 'failed'}>ทำ</Button>
                            </form>
                            {#if deletable}
                                <form
                                    method="POST"
                                    action="?/deleteExercise"
                                    use:enhance={confirmed('ต้องการลบแบบฝึกหัดชุดนี้ใช่หรือไม่')}
                                >
                                    <input type="hidden" name="exercise_id" value={exercise.exercise_id} />
                                    <Button size="sm" color="rose">ลบ</Button>
                                </form>
                            {/if}
                        </div>
                    </td>
                </tr>
            {/each}
        </tbody>
    </table>
</div>
