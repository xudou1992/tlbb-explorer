# -*- coding: utf-8 -*-
"""修复 browse.js 两处:filter guard 的损坏串 + openPak 自动重试。"""
import io

p = r'D:/TLGL/tlbb-explorer/app/web/browse.js'
s = io.open(p, encoding='utf-8').read()

# 1. 补回被 shell 吃掉的模板串
broken = '''        appendMsg(el("treeBody"), currentPak
          ?
          : "先在左边打开一个 data 再搜索。");'''
fixed = '''        appendMsg(el("treeBody"), currentPak
          ? `「${currentPak}」还没就绪，等它打开后再搜。`
          : "先在左边打开一个 data 再搜索。");'''
assert broken in s, 'broken filter region not found'
s = s.replace(broken, fixed)

# 2. openPak 失败自动重试(第二次替换之前没生效)
broken2 = '''  } catch (e) {
    if (my !== pakSeq) return; // 迟到的失败也一样，别去动新包的界面
    el("treeTitle").textContent = `${name} · 打开失败`; // 标题不能永远停在「正在打开」
    el("treeFilter").hidden = true; // 没有树可搜，搜索框空挂着只会让人白打字
    el("treeBody").innerHTML = "";
    appendMsg(el("treeBody"), String(e?.message || e));
  }
}'''
fixed2 = '''  } catch (e) {
    if (my !== pakSeq) return; // 迟到的失败也一样，别去动新包的界面
    // 后端树有进程级缓存，重试几乎必然命中缓存秒回——自动补一次，别把
    // 「偶发失败」留给用户面对一棵死树和死搜索框。
    setTimeout(() => {
      if (my === pakSeq && tree === null) openPak(name);
    }, 2500);
    el("treeTitle").textContent = `${name} · 打开失败，正在自动重试`;
    el("treeFilter").hidden = true; // 没有树可搜，搜索框空挂着只会让人白打字
    el("treeBody").innerHTML = "";
    appendMsg(el("treeBody"), String(e?.message || e));
  }
}'''
assert broken2 in s, 'catch region not found'
s = s.replace(broken2, fixed2)

io.open(p, 'w', encoding='utf-8', newline='').write(s)
print('both patches applied')
