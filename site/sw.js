// Trailer Docs service worker -- the whole point of the hosted copy.
// The cache name carries the build version, so publishing a new version
// installs a fresh cache and drops the old one.
const CACHE = 'trailer-docs-1.3.4';

// Every photo is precached at install, not lazily on first view: a phone that
// installs at the office and then drives to a field with no signal has to have
// all of them already.
//
// The split matters. SHELL files keep the same URL every build, so a new
// worker has to refetch them or it would serve the previous app forever.
// PHOTO urls carry a content hash, so a url that still matches is
// byte-identical and can be copied straight out of the old cache -- no
// network at all. Pages serves Cache-Control: max-age=600, so ten minutes
// after a build, refetching would put 37 revalidation round trips between a
// weak signal and a working app, for photos the phone already has.
const SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon-180.png",
  "./icon-192.png",
  "./icon-512.png"
];
const PHOTOS = [
  "./photos/setup-32_amp_port.33434b3a.webp",
  "./photos/setup-closed_side.89f2c7e3.webp",
  "./photos/setup-corner_ratchet_flocked.288aada7.webp",
  "./photos/setup-distro.1f4c7c09.webp",
  "./photos/setup-distro_breakers.cb383c80.webp",
  "./photos/setup-door_bolt.e8499eaf.webp",
  "./photos/setup-door_frames.8908ef87.webp",
  "./photos/setup-frame_20_espa.49874233.webp",
  "./photos/setup-full_rig_oppen.aac55b59.webp",
  "./photos/setup-green_pin.3eb9aec8.webp",
  "./photos/setup-hydrolics_off.0625eb2a.webp",
  "./photos/setup-left_side_unfurled.50907241.webp",
  "./photos/setup-manual_overide.23ebf400.webp",
  "./photos/setup-manual_override_pilons.3bf96723.webp",
  "./photos/setup-multi-plug.3da03a75.webp",
  "./photos/setup-opening_side_panel.ad92dfa9.webp",
  "./photos/setup-plug_around_light.592e5448.webp",
  "./photos/setup-red_cable_as_handle.e4ccc3d6.webp",
  "./photos/setup-red_carabiner_attach_point.96ece61e.webp",
  "./photos/setup-red_handle.0bb27d42.webp",
  "./photos/setup-roof_up_side.60735cea.webp",
  "./photos/setup-side_lowered.0f00ffb2.webp",
  "./photos/setup-side_lowering.84bc3811.webp",
  "./photos/setup-side_panel_open.d1a7c21d.webp",
  "./photos/setup-side_pin_alignment.b9d5f96d.webp",
  "./photos/setup-side_pin_out.6c1b39dd.webp",
  "./photos/setup-sides_wall_open.6374ee5f.webp",
  "./photos/setup-sny_kettle_around_light.82348310.webp",
  "./photos/setup-sony_espa_powered_on.8aa79575.webp",
  "./photos/setup-sony_power.dd5220e9.webp",
  "./photos/setup-spring_bolt_under_side.1b68be75.webp",
  "./photos/setup-spring_bolt_under_side_open.1ace01ea.webp",
  "./photos/setup-support_leg.0197e30d.webp",
  "./photos/setup-support_leg_attached.4edf2c12.webp",
  "./photos/setup-wall_bolts.5b376f39.webp",
  "./photos/setup-white_panel_bolt_closed.3e92959e.webp",
  "./photos/setup-white_panel_bolt_open.57c3a463.webp"
];

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL);

    const carried = new Set();
    for (const key of (await caches.keys()).filter(k => k !== CACHE)) {
      const prev = await caches.open(key);
      for (const url of PHOTOS) {
        if (carried.has(url)) continue;
        const hit = await prev.match(url);
        if (hit) { await cache.put(url, hit); carried.add(url); }
      }
    }

    const fresh = PHOTOS.filter(u => !carried.has(u));
    if (fresh.length) await cache.addAll(fresh);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Cache first: on set there is often a weak signal, and waiting on the network
// is worse than serving the copy we already have. A background fetch refreshes
// the cache for next launch.
self.addEventListener('fetch', e => {
  const req = e.request;
  if(req.method !== 'GET') return;
  e.respondWith(
    caches.match(req, {ignoreSearch: true}).then(hit => {
      const net = fetch(req).then(res => {
        if(res && res.ok && new URL(req.url).origin === self.location.origin){
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => null);
      if(hit) return hit;
      return net.then(res => res || (req.mode === 'navigate'
        ? caches.match('./index.html') : Response.error()));
    })
  );
});
