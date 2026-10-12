import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class FACOResourceWatch extends Extension {
    enable() {
        const layout = new St.BoxLayout({style_class: 'faco-watch-layout'});
        this._label = new St.Label({text: 'CPU —  RAM —  GPU —',
            y_align: 2, style_class: 'faco-watch-text'});
        layout.add_child(this._label);
        this._button = new St.Button({
            style_class: 'panel-button faco-watch-button',
            reactive: true, can_focus: true, track_hover: true,
            child: layout,
        });
        this._clickedId = this._button.connect('clicked', () => this._openDashboard());
        // Intentionally place FIRST in the center box, to the LEFT of the clock.
        // Center box placement uses an internal GNOME API: if GNOME changes it,
        // we fall back to the regular left-side panel box rather than crashing.
        const box = Main.panel._centerBox ?? Main.panel._leftBox;
        box.insert_child_at_index(this._button, 0);
        this._update();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._update();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _update() {
        if (!this._label) return;
        const dir = GLib.getenv('XDG_RUNTIME_DIR') || GLib.get_user_runtime_dir();
        const file = Gio.File.new_for_path(GLib.build_filenamev([
            dir, 'faco-resource-watch', 'latest.json'
        ]));
        try {
            const [ok, bytes] = file.load_contents(null);
            if (!ok) throw Error('File not ready');
            const data = JSON.parse(new TextDecoder('utf-8').decode(bytes));
            if (!data.ts || (Date.now() / 1000 - data.ts) > 12) {
                this._label.set_text('FACO: OFFLINE');
                return;
            }
            const cpu = this._pct(data.cpu_percent);
            const ram = this._pct(data.ram?.percent);
            const cpuTemp = this._temp(data.cpu_temp_c);
            const gpu = data.gpus?.[0];
            const gpuPct = this._pct(gpu?.percent);
            const gpuTemp = this._temp(gpu?.temp_c);
            const used = this._gib(gpu?.vram_used_bytes);
            const total = this._gib(gpu?.vram_total_bytes);
            const video = gpu ? ` GPU ${gpuPct} ${gpuTemp} VRAM ${used}/${total}` : ' GPU —';
            this._label.set_text(`CPU ${cpu} ${cpuTemp} RAM ${ram}${video}`);
        } catch (_) {
            this._label.set_text('FACO: STARTING…');
        }
    }

    _pct(v) {
        return v === null || v === undefined || !Number.isFinite(Number(v))
            ? '—' : `${Math.round(Number(v))}%`;
    }
    _temp(v) {
        return v === null || v === undefined || !Number.isFinite(Number(v))
            ? '—' : `${Math.round(Number(v))}°`;
    }
    _gib(v) {
        return v === null || v === undefined || !Number.isFinite(Number(v))
            ? '—' : `${(Number(v) / 1073741824).toFixed(1)}G`;
    }

    _openDashboard() {
        const executable = GLib.build_filenamev([
            GLib.get_home_dir(), '.local', 'bin', 'faco-resource-watch'
        ]);
        if (!GLib.file_test(executable, GLib.FileTest.EXISTS)) {
            Main.notify('FACO Resource Watch', 'Launcher not installed. Run install.sh.');
            return;
        }
        try {
            Gio.Subprocess.new([executable, 'open'], Gio.SubprocessFlags.NONE);
        } catch (e) {
            Main.notify('FACO Resource Watch', `Dashboard launch failed: ${e.message}`);
        }
    }

    disable() {
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = 0;
        }
        if (this._button) {
            if (this._clickedId) this._button.disconnect(this._clickedId);
            this._button.destroy();
            this._button = null;
        }
        this._label = null;
    }
}
