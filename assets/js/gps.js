/**
 * RAKSHA-FORCE — GPS Location Manager
 * ─────────────────────────────────────────────────────────────
 * Usage:
 *   const gps = new GPSManager({ onUpdate, onError, context: 'admin' });
 *   gps.start();  // begins watching
 *   gps.stop();   // clears watcher
 *   gps.once();   // single read
 *   gps.getPosition() // returns { lat, lng, accuracy, timestamp }
 *
 * Features:
 *  - Handles all permission states (granted / denied / prompt)
 *  - Writes to Supabase gps_locations table (if user logged in)
 *  - Fires callbacks on update and error
 *  - Exposes last known position
 *  - Works with Leaflet map if provided
 */

class GPSManager {
  /**
   * @param {Object} opts
   * @param {function} opts.onUpdate  (pos: {lat,lng,accuracy,timestamp}) => void
   * @param {function} opts.onError   (msg: string) => void
   * @param {string}   opts.context   Page context label for DB ('citizen'|'admin'|'report')
   * @param {Object}   opts.mapInstance  Leaflet map instance (optional)
   * @param {string}   opts.userId    Supabase user id (optional, for DB writes)
   * @param {boolean}  opts.saveToDb  Whether to save coordinates to Supabase
   */
  constructor(opts = {}) {
    this.onUpdate   = opts.onUpdate   || (() => {});
    this.onError    = opts.onError    || (() => {});
    this.context    = opts.context    || 'unknown';
    this.map        = opts.mapInstance || null;
    this.userId     = opts.userId     || null;
    this.saveToDb   = opts.saveToDb   !== false; // default true

    this._watchId        = null;
    this._lastPosition   = null;
    this._marker         = null;
    this._circle         = null;
    this._saveInterval   = null;

    this.GEO_OPTIONS = {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 5000,
    };
  }

  /** Check if browser supports geolocation */
  isSupported() {
    return 'geolocation' in navigator;
  }

  /** Check current permission state (returns 'granted'|'denied'|'prompt'|'unknown') */
  async checkPermission() {
    if (!navigator.permissions) return 'unknown';
    try {
      const status = await navigator.permissions.query({ name: 'geolocation' });
      return status.state; // 'granted' | 'denied' | 'prompt'
    } catch {
      return 'unknown';
    }
  }

  /** Get position once */
  once() {
    return new Promise((resolve, reject) => {
      if (!this.isSupported()) {
        const msg = 'Geolocation not supported by this browser.';
        this.onError(msg);
        reject(new Error(msg));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const position = this._processPosition(pos);
          resolve(position);
        },
        (err) => {
          const msg = this._errorMessage(err);
          this.onError(msg);
          reject(new Error(msg));
        },
        this.GEO_OPTIONS
      );
    });
  }

  /** Start continuous watching */
  start() {
    if (!this.isSupported()) {
      this.onError('Geolocation is not supported by your browser.');
      return;
    }
    if (this._watchId !== null) return; // already watching

    this._watchId = navigator.geolocation.watchPosition(
      (pos) => this._processPosition(pos),
      (err) => {
        const msg = this._errorMessage(err);
        this.onError(msg);
      },
      this.GEO_OPTIONS
    );

    // Throttle DB writes to every 30 seconds
    if (this.saveToDb && window.RF) {
      this._saveInterval = setInterval(() => {
        if (this._lastPosition && this.userId) {
          window.RF.saveGPS({
            userId: this.userId,
            lat: this._lastPosition.lat,
            lng: this._lastPosition.lng,
            context: this.context,
            accuracy: this._lastPosition.accuracy,
          }).catch(() => {});
        }
      }, 30000);
    }
  }

  /** Stop watching */
  stop() {
    if (this._watchId !== null) {
      navigator.geolocation.clearWatch(this._watchId);
      this._watchId = null;
    }
    if (this._saveInterval) {
      clearInterval(this._saveInterval);
      this._saveInterval = null;
    }
  }

  /** Return last known position or null */
  getPosition() {
    return this._lastPosition;
  }

  /** Attach to a Leaflet map instance after construction */
  setMap(mapInstance) {
    this.map = mapInstance;
    if (this._lastPosition) this._updateMap(this._lastPosition);
  }

  // ── Private ──────────────────────────────────────────────────

  _processPosition(raw) {
    const position = {
      lat:       raw.coords.latitude,
      lng:       raw.coords.longitude,
      accuracy:  raw.coords.accuracy,      // metres
      altitude:  raw.coords.altitude,
      speed:     raw.coords.speed,
      heading:   raw.coords.heading,
      timestamp: raw.timestamp,
    };
    this._lastPosition = position;
    this.onUpdate(position);
    if (this.map) this._updateMap(position);
    return position;
  }

  _updateMap(pos) {
    if (!this.map || !window.L) return;
    const latlng = [pos.lat, pos.lng];

    if (!this._marker) {
      // Create pulsing marker
      const icon = L.divIcon({
        html: `<div class="gps-marker-outer"><div class="gps-marker-inner"></div></div>`,
        className: '',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      });
      this._marker = L.marker(latlng, { icon, zIndexOffset: 1000 }).addTo(this.map);
      this._marker.bindPopup('<b>📍 Your Location</b>');

      // Accuracy circle
      this._circle = L.circle(latlng, {
        radius: pos.accuracy || 50,
        color: '#003087',
        fillColor: '#003087',
        fillOpacity: 0.06,
        weight: 1,
      }).addTo(this.map);
    } else {
      this._marker.setLatLng(latlng);
      this._circle.setLatLng(latlng);
      this._circle.setRadius(pos.accuracy || 50);
    }
  }

  _errorMessage(err) {
    switch (err.code) {
      case err.PERMISSION_DENIED:
        return 'Location permission denied. Please allow location access in your browser settings.';
      case err.POSITION_UNAVAILABLE:
        return 'Location information unavailable. Check your device GPS.';
      case err.TIMEOUT:
        return 'Location request timed out. Please try again.';
      default:
        return `Location error: ${err.message}`;
    }
  }
}

/**
 * GPS Status Widget — renders a small indicator into any element.
 * Params: containerId (string), gpsManager (GPSManager instance)
 */
function renderGPSWidget(containerId, gpsManager) {
  const el = document.getElementById(containerId);
  if (!el) return;

  function update(pos) {
    el.innerHTML = `
      <div class="gps-widget gps-ok">
        <span class="gps-icon">📍</span>
        <div class="gps-details">
          <span class="gps-coords">${pos.lat.toFixed(5)}, ${pos.lng.toFixed(5)}</span>
          <span class="gps-accuracy">±${Math.round(pos.accuracy || 0)}m accuracy</span>
        </div>
      </div>`;
  }

  function error(msg) {
    el.innerHTML = `
      <div class="gps-widget gps-err">
        <span class="gps-icon">⚠️</span>
        <span class="gps-coords">${msg}</span>
      </div>`;
  }

  gpsManager.onUpdate = (pos) => { update(pos); if (gpsManager._origOnUpdate) gpsManager._origOnUpdate(pos); };
  gpsManager.onError  = (msg) => { error(msg);  if (gpsManager._origOnError)  gpsManager._origOnError(msg); };

  el.innerHTML = `<div class="gps-widget gps-loading"><span class="gps-icon">🛰️</span><span class="gps-coords">Acquiring GPS...</span></div>`;
}

// Inject GPS widget CSS once
(function injectGPSStyles() {
  if (document.getElementById('gps-styles')) return;
  const style = document.createElement('style');
  style.id = 'gps-styles';
  style.textContent = `
    .gps-widget { display:flex; align-items:center; gap:8px; font-family:'Rajdhani',sans-serif; font-size:12px; padding:6px 10px; border-radius:2px; }
    .gps-ok     { background:rgba(0,204,102,0.08); border:1px solid rgba(0,204,102,0.25); color:#00CC66; }
    .gps-err    { background:rgba(200,16,46,0.08); border:1px solid rgba(200,16,46,0.25); color:#C8102E; }
    .gps-loading{ background:rgba(0,48,135,0.08);  border:1px solid rgba(0,48,135,0.25);  color:#6B9FE0; }
    .gps-details { display:flex; flex-direction:column; }
    .gps-coords { font-weight:600; letter-spacing:0.3px; }
    .gps-accuracy{ font-size:10px; opacity:0.7; }
    .gps-marker-outer {
      width:20px; height:20px; border-radius:50%;
      background:rgba(0,48,135,0.25);
      border:2px solid #003087;
      display:flex; align-items:center; justify-content:center;
      animation:gpsPulse 2s ease-in-out infinite;
    }
    .gps-marker-inner {
      width:8px; height:8px; border-radius:50%;
      background:#003087;
    }
    @keyframes gpsPulse {
      0%,100% { box-shadow:0 0 0 0 rgba(0,48,135,0.4); }
      50%     { box-shadow:0 0 0 8px rgba(0,48,135,0); }
    }
  `;
  document.head.appendChild(style);
})();

// Export
if (typeof window !== 'undefined') {
  window.GPSManager = GPSManager;
  window.renderGPSWidget = renderGPSWidget;
}
