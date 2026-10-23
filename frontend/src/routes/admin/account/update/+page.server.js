import { fail, redirect } from '@sveltejs/kit';
import { api, getJson } from '#lib/server/api.js';

export async function load(event) {
    const account = await getJson(event, `/admin/users/${event.url.searchParams.get('user_id')}`);
    const [name, ...surname] = account.full_name.split(' ');
    return { account: { ...account, name, surname: surname.join(' ') } };
}

export const actions = {
    default: async (event) => {
        const form = await event.request.formData();
        const response = await api(event, `/admin/users/${form.get('user_id')}`, {
            method: 'PATCH',
            body: {
                username: form.get('username'),
                member_id: form.get('member_id'),
                password: form.get('password') || null,
                full_name: `${form.get('name')} ${form.get('surname')}`,
                role: form.get('role')
            }
        });
        if (!response.ok) return fail(400, { message: 'ไม่สามารถแก้ไขข้อมูลของนี้บัญชีได้' });
        redirect(303, '/admin/dashboard');
    }
};
