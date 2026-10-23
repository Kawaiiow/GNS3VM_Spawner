import { fail } from '@sveltejs/kit';
import { api } from '#lib/server/api.js';
import { instanceActions, loadDashboard } from '#lib/server/instances.js';

export const load = loadDashboard;

export const actions = {
    ...instanceActions,
    deleteExercise: async (event) => {
        const form = await event.request.formData();
        const response = await api(event, `/exercises/${form.get('exercise_id')}`, { method: 'DELETE' });
        if (!response.ok) return fail(400, { message: 'ไม่สามารถลบแบบฝึกหัดได้' });
    }
};
