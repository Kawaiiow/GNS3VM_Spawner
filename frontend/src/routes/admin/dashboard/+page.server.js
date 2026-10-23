import { fail } from '@sveltejs/kit';
import { api, getJson } from '#lib/server/api.js';

export async function load(event) {
    return { users: await getJson(event, '/admin/dashboard') };
}

export const actions = {
    delete: async (event) => {
        const form = await event.request.formData();
        const response = await api(event, `/admin/users/${form.get('user_id')}`, { method: 'DELETE' });
        if (!response.ok) return fail(400, { message: 'ไม่สามารถลบบัญชีนี้ได้' });
    }
};
