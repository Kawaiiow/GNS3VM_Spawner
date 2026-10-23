import { fail, redirect } from '@sveltejs/kit';
import { api } from '#lib/server/api.js';
import { dashboardPath, redirectIfSignedIn } from '#lib/server/session.js';

export const load = redirectIfSignedIn;

export const actions = {
    default: async (event) => {
        const form = await event.request.formData();
        const response = await api(event, '/auth/login', {
            method: 'POST',
            body: { identifier: form.get('identifier'), password: form.get('password') }
        });
        if (!response.ok) return fail(400, { message: 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง' });

        const { access_token, user } = await response.json();
        const options = {
            httpOnly: true,
            secure: event.url.protocol === 'https:',
            sameSite: 'lax',
            maxAge: 60 * 60 * 24
        };
        event.cookies.set('access_token', access_token, options);
        event.cookies.set('username', user.username, options);
        event.cookies.set('role', user.role, options);
        redirect(303, dashboardPath(user.role));
    }
};
