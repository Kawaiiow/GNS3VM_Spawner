import { redirectIfSignedIn } from '#lib/server/session.js';

export const load = redirectIfSignedIn;
