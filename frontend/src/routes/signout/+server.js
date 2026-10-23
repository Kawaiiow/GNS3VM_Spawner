import { redirect } from '@sveltejs/kit';
import { api } from '#lib/server/api.js';

export async function POST(event) {
    await api(event, '/auth/logout', { method: 'POST' });
    for (const name of ['access_token', 'username', 'role']) event.cookies.delete(name, { path: '/' });
    redirect(303, '/');
}
