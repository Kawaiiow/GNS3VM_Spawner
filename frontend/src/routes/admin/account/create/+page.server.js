import { fail, redirect } from '@sveltejs/kit';
import { api, getJson } from '#lib/server/api.js';

export async function load(event) {
    await getJson(event, '/auth/me');
}

export const actions = {
    default: async (event) => {
        const form = await event.request.formData();
        const response = await api(event, '/admin/users', {
            method: 'POST',
            body: {
                username: form.get('username'),
                member_id: form.get('member_id'),
                password: form.get('password'),
                full_name: `${form.get('name')} ${form.get('surname')}`,
                role: form.get('role')
            }
        });
        if (!response.ok) return fail(400, { message: 'ไม่สามารถสร้างบัญชีใหม่ได้' });
        redirect(303, '/admin/dashboard');
    }
};
