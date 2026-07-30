// === config.js ===
// Fill in your Supabase project anon key (NOT service_role) below.
// Get it at: https://supabase.com/dashboard/project/adfirxacvkcoasbujbgo/api
// It looks like: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
const CONFIG = {
  SUPABASE_URL: 'https://adfirxacvkcoasbujbgo.supabase.co',
  SUPABASE_ANON_KEY: 'TODO_PASTE_ANON_KEY_HERE',
  SUPABASE_REST: 'https://adfirxacvkcoasbujbgo.supabase.co/rest/v1',
  // Music ideas data dir on hi168 S3 (public)
  S3_BASE: 'https://hi168-hv6u2fnwrvs-jnilusqt-s.s3.hi168.com',
  // Today's date string (auto-filled)
  TODAY: new Date().toISOString().slice(0, 10),
};