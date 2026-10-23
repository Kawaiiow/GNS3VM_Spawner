import { fail, redirect } from '@sveltejs/kit';
import { api, getJson } from '#lib/server/api.js';

export async function load(event) {
    const instanceId = event.url.searchParams.get('instance_id');
    const { projects } = await getJson(event, `/instances/${instanceId}/gns3/projects`);
    return { instanceId, projects };
}

export const actions = {
    default: async (event) => {
        const form = await event.request.formData();
        const response = await api(event, '/exercises', {
            method: 'POST',
            body: {
                instance_id: form.get('instance_id'),
                title: form.get('title'),
                description: form.get('description'),
                project_ids: form.getAll('project_ids')
            }
        });
        if (!response.ok) return fail(400, { message: 'ไม่สามารถเพิ่มแบบฝึกหัดใหม่ได้' });
        redirect(303, '/instructor/dashboard');
    }
};
