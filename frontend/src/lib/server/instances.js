import { fail } from '@sveltejs/kit';
import { api, getJson } from './api.js';

const instanceAction = (method, path, message, timeout) => async (event) => {
    const form = await event.request.formData();
    const response = await api(event, `/instances/${form.get('instance_id')}${path}`, {
        method,
        timeout
    });
    if (!response.ok) return fail(400, { message });
};

export const instanceActions = {
    create: async (event) => {
        const form = await event.request.formData();
        const exerciseId = form.get('exercise_id');
        const kind = exerciseId ? 'exercise' : 'sandbox';
        const response = await api(event, '/instances', {
            method: 'POST',
            body: { instance_name: `gns3-${event.cookies.get('username')}-${kind}`, exercise_id: exerciseId }
        });
        if (!response.ok) return fail(400, { message: 'ไม่สามารถสร้างเครื่องใหม่ได้' });
    },
    start: instanceAction('POST', '/start', 'ไม่สามารถเปิดเครื่องนี้ได้', 150000),
    stop: instanceAction('POST', '/stop', 'ไม่สามารถหยุดเครื่องนี้ได้'),
    extend: instanceAction('POST', '/extend', 'ไม่สามารถเพิ่มเวลาเครื่องนี้ได้'),
    delete: instanceAction('DELETE', '', 'ไม่สามารถลบเครื่องนี้ได้')
};

export async function loadDashboard(event) {
    const [{ instances }, { exercises }] = await Promise.all([
        getJson(event, '/instances'),
        getJson(event, '/exercises')
    ]);
    return { instances, exercises };
}
