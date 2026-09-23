//! RGBA → PNG.

use std::fs::File;
use std::io::{BufWriter, Cursor};
use std::path::Path;



pub fn png_bytes(width: u16, height: u16, rgba: &[u8], fast: bool) -> Result<Vec<u8>, String> {
    let need = width as usize * height as usize * 4;
    if rgba.len() < need {
        return Err(format!("rgba buffer {} < {need}", rgba.len()));
    }
    let mut buf = Cursor::new(Vec::new());
    {
        let mut enc = png::Encoder::new(&mut buf, width as u32, height as u32);
        enc.set_color(png::ColorType::Rgba);
        enc.set_depth(png::BitDepth::Eight);
        enc.set_compression(if fast {
            png::Compression::Fast
        } else {
            png::Compression::Best
        });
        let mut w = enc.write_header().map_err(|e| e.to_string())?;
        w.write_image_data(&rgba[..need]).map_err(|e| e.to_string())?;
    }
    Ok(buf.into_inner())
}

pub fn write_png(path: &Path, width: u16, height: u16, rgba: &[u8]) -> Result<(), String> {
    let bytes = png_bytes(width, height, rgba, false)?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let mut f = BufWriter::new(File::create(path).map_err(|e| e.to_string())?);
    std::io::Write::write_all(&mut f, &bytes).map_err(|e| e.to_string())
}

/// Box-filter downscale to fit inside `max` pixels on the longest edge, keeping aspect.
/// Good enough for thumbnails and cheap enough to run over the whole corpus.
pub fn scale_rgba(rgba: &[u8], w: usize, h: usize, max: usize) -> (Vec<u8>, usize, usize) {
    if w == 0 || h == 0 || w.max(h) <= max {
        return (rgba.to_vec(), w, h);
    }
    let tw = ((w * max) as f64 / h.max(1) as f64).round().max(1.0) as usize;
    let (nw, nh) = if w >= h { (max, tw.min(max)) } else { (tw, max) };
    let (nw, nh) = (nw.max(1), nh.max(1));
    let mut out = vec![0u8; nw * nh * 4];
    let xw = w as f64 / nw as f64;
    let yh = h as f64 / nh as f64;
    for y in 0..nh {
        let y0 = (y as f64 * yh) as usize;
        let y1 = ((y + 1) as f64 * yh).floor() as usize;
        let y1 = y1.max(y0 + 1).min(h);
        for x in 0..nw {
            let x0 = (x as f64 * xw) as usize;
            let x1 = ((x + 1) as f64 * xw).floor() as usize;
            let x1 = x1.max(x0 + 1).min(w);
            let (mut r, mut g, mut b, mut a, mut n) = (0u32, 0u32, 0u32, 0u32, 0u32);
            for sy in y0..y1 {
                for sx in x0..x1 {
                    let o = (sy * w + sx) * 4;
                    r += rgba[o] as u32;
                    g += rgba[o + 1] as u32;
                    b += rgba[o + 2] as u32;
                    a += rgba[o + 3] as u32;
                    n += 1;
                }
            }
            let o = (y * nw + x) * 4;
            let n = n.max(1);
            out[o] = (r / n) as u8;
            out[o + 1] = (g / n) as u8;
            out[o + 2] = (b / n) as u8;
            out[o + 3] = (a / n) as u8;
        }
    }
    (out, nw, nh)
}
