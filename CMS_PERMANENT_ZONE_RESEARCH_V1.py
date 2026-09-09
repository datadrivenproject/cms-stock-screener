import streamlit as st
import pandas as pd
import numpy as np
import requests
import hashlib
import plotly.graph_objects as go

st.set_page_config(page_title='CMS Permanent Zone Research v1', layout='wide')

UNIVERSE = [
'AAPL','MSFT','NVDA','AMZN','META','GOOGL','TSLA','AVGO','AMD','NFLX','ORCL','IBM','DELL','HPE','SMCI',
'CRM','ADBE','NOW','PLTR','PATH','CRWD','PANW','FTNT','DDOG','NET','SNOW','MDB','ZS','OKTA','TEAM',
'QCOM','MU','INTC','ARM','MRVL','AMAT','LRCX','KLAC','ON','MCHP','JPM','BAC','WFC','GS','MS','V','MA','AXP','PYPL','COIN','HOOD','SOFI','XYZ','NU','IBKR',
'LLY','UNH','ABBV','MRK','AMGN','JNJ','PFE','GILD','ISRG','TMO','TEM','VEEV','REGN','VRTX','DXCM','XOM','CVX','COP','CAT','GE','BA','RTX','LMT','ETN','VRT','PLUG','FCX','SLB','FSLR','CEG',
'WMT','COST','HD','DIS','UBER','ABNB','DASH','BKNG','SHOP','MELI','RBLX','SPOT','ROKU','DUOL','RDDT','CRCL','APP','RKLB','ASTS','IONQ','RGTI','SOUN','HIMS','CAVA','CVNA'
]


def _walk_secret(obj, key):
    try:
        if key in obj:
            return obj[key]
    except Exception:
        pass
    try:
        for _, v in obj.items():
            if hasattr(v, 'items'):
                out = _walk_secret(v, key)
                if out is not None:
                    return out
    except Exception:
        pass
    return None


def get_supabase_config():
    url = _walk_secret(st.secrets, 'SUPABASE_URL')
    key = _walk_secret(st.secrets, 'SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        raise RuntimeError('Streamlit Secrets 缺少 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY。')
    url = str(url).strip().rstrip('/')
    if '/rest/v1' in url:
        url = url.split('/rest/v1', 1)[0].rstrip('/')
    return url, str(key).strip()


def split_chunks(items, n=20):
    for i in range(0, len(items), n):
        yield items[i:i+n]


def rows_to_df(rows):
    if not rows:
        return None
    d = pd.DataFrame(rows)
    req = ['trade_date','adj_open','adj_high','adj_low','adj_close','volume']
    if any(c not in d.columns for c in req):
        return None
    d['trade_date'] = pd.to_datetime(d['trade_date'], errors='coerce')
    for c in req[1:]:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=req).sort_values('trade_date').drop_duplicates('trade_date', keep='last')
    if d.empty:
        return None
    d = d.set_index('trade_date')
    d.index.name = 'Date'
    return d.rename(columns={'adj_open':'Open','adj_high':'High','adj_low':'Low','adj_close':'Close','volume':'Volume'})[['Open','High','Low','Close','Volume']]


def load_snapshot(tickers):
    base, key = get_supabase_config()
    endpoint = f'{base}/rest/v1/stock_daily'
    headers = {'apikey':key,'Authorization':f'Bearer {key}','Accept':'application/json'}
    rows_by = {t:[] for t in tickers}
    for chunk in split_chunks(tickers, 20):
        start = 0
        while True:
            params = {
                'select':'ticker,trade_date,adj_open,adj_high,adj_low,adj_close,volume',
                'ticker':'in.(' + ','.join(chunk) + ')',
                'order':'ticker.asc,trade_date.asc'
            }
            h = dict(headers); h['Range'] = f'{start}-{start+999}'
            r = requests.get(endpoint, params=params, headers=h, timeout=60)
            if not r.ok:
                raise RuntimeError(f'Supabase HTTP {r.status_code}: {r.text[:400]}')
            page = r.json()
            for row in page:
                t = str(row.get('ticker','')).upper()
                if t in rows_by:
                    rows_by[t].append(row)
            if len(page) < 1000:
                break
            start += 1000
    out = {}
    for t, rows in rows_by.items():
        df = rows_to_df(rows)
        if df is not None and len(df) >= 80:
            out[t] = df
    return out


def add_atr(df, period=14):
    d = df.copy()
    pc = d['Close'].shift(1)
    tr = pd.concat([(d['High']-d['Low']).abs(), (d['High']-pc).abs(), (d['Low']-pc).abs()], axis=1).max(axis=1)
    d['ATR'] = tr.rolling(period, min_periods=5).mean()
    return d


def detect_pivots(df, left=3, right=3, reaction_atr=0.8, reaction_bars=5):
    d = add_atr(df)
    pivots=[]
    for i in range(left, len(d)-max(right, reaction_bars)):
        hi = d['High'].iloc[i]; lo = d['Low'].iloc[i]; atr = d['ATR'].iloc[i]
        if pd.isna(atr) or atr <= 0: continue
        win_hi = d['High'].iloc[i-left:i+right+1]
        win_lo = d['Low'].iloc[i-left:i+right+1]
        future = d.iloc[i+1:i+1+reaction_bars]
        if hi >= win_hi.max():
            reaction = (hi - future['Low'].min())/atr if not future.empty else 0
            if reaction >= reaction_atr:
                pivots.append({'idx':i,'date':d.index[i],'type':'R','price':float(hi),'atr':float(atr),'reaction':float(reaction)})
        if lo <= win_lo.min():
            reaction = (future['High'].max() - lo)/atr if not future.empty else 0
            if reaction >= reaction_atr:
                pivots.append({'idx':i,'date':d.index[i],'type':'S','price':float(lo),'atr':float(atr),'reaction':float(reaction)})
    return sorted(pivots, key=lambda x:x['idx'])


def zone_id(ticker, ztype, confirmed_date, lo, hi):
    raw=f'{ticker}|{ztype}|{confirmed_date.date()}|{lo:.4f}|{hi:.4f}'
    return f'{ticker}-{ztype}-' + hashlib.md5(raw.encode()).hexdigest()[:7].upper()


def build_frozen_zones(ticker, df, cluster_atr=0.5, min_gap=5, confirm_touches=3):
    pivots = detect_pivots(df)
    zones=[]
    candidates=[]
    for p in pivots:
        matched=None
        # confirmed zones first: boundary is frozen forever
        for z in zones:
            if z['origin_type'] != p['type']: continue
            if p['idx'] - z['last_touch_idx'] < min_gap: continue
            tol = max(cluster_atr*p['atr'], 0.0025*p['price'])
            if z['low']-tol <= p['price'] <= z['high']+tol:
                matched=z; break
        if matched is not None:
            matched['touches'] += 1
            matched['last_touch_date'] = p['date']
            matched['last_touch_idx'] = p['idx']
            matched['max_reaction_atr'] = max(matched['max_reaction_atr'], p['reaction'])
            continue
        # candidate zones can move only before confirmation
        cm=None
        for c in candidates:
            if c['type'] != p['type']: continue
            if p['idx'] - c['last_idx'] < min_gap: continue
            center=np.mean(c['prices'])
            tol=max(cluster_atr*p['atr'], 0.0025*p['price'])
            if abs(p['price']-center) <= tol:
                cm=c; break
        if cm is None:
            candidates.append({'type':p['type'],'prices':[p['price']],'atrs':[p['atr']],'dates':[p['date']],'idxs':[p['idx']],'reactions':[p['reaction']], 'last_idx':p['idx']})
        else:
            cm['prices'].append(p['price']); cm['atrs'].append(p['atr']); cm['dates'].append(p['date']); cm['idxs'].append(p['idx']); cm['reactions'].append(p['reaction']); cm['last_idx']=p['idx']
            if len(cm['prices']) >= confirm_touches:
                # freeze zone ON confirmation; never move boundaries later
                center=float(np.median(cm['prices']))
                atr0=float(np.median(cm['atrs']))
                half=max(0.25*atr0, 0.003*center)
                lo=center-half; hi=center+half
                z={
                    'ticker':ticker,'origin_type':cm['type'],'low':lo,'high':hi,'center':center,
                    'confirmed_date':cm['dates'][-1], 'first_touch_date':cm['dates'][0], 'last_touch_date':cm['dates'][-1],
                    'touches':len(cm['prices']), 'last_touch_idx':cm['idxs'][-1], 'max_reaction_atr':max(cm['reactions'])
                }
                z['zone_id']=zone_id(ticker, z['origin_type'], z['confirmed_date'], lo, hi)
                zones.append(z); candidates.remove(cm)
    # retain 2-touch candidates for research display
    cand_rows=[]
    for c in candidates:
        if len(c['prices']) >= 2:
            center=float(np.median(c['prices'])); atr0=float(np.median(c['atrs'])); half=max(0.25*atr0,0.003*center)
            cand_rows.append({'ticker':ticker,'origin_type':c['type'],'low':center-half,'high':center+half,'center':center,
                              'confirmed_date':pd.NaT,'first_touch_date':c['dates'][0],'last_touch_date':c['dates'][-1],
                              'touches':len(c['prices']),'zone_id':'候选','max_reaction_atr':max(c['reactions'])})
    # Current status: boundary stays fixed; only status changes.
    last_close=float(df['Close'].iloc[-1])
    for z in zones:
        if z['origin_type']=='R':
            if last_close > z['high']*1.005: status='已突破原压力'
            elif z['low'] <= last_close <= z['high']: status='正在测试压力'
            elif last_close < z['low']: status='压力仍在上方'
            else: status='原压力附近'
        else:
            if last_close < z['low']*0.995: status='已跌破原支撑'
            elif z['low'] <= last_close <= z['high']: status='正在测试支撑'
            elif last_close > z['high']: status='支撑仍在下方'
            else: status='原支撑附近'
        z['status']=status
    return zones, cand_rows, pivots


def strength_label(n):
    if n >= 5: return '非常强'
    if n == 4: return '强'
    if n >= 3: return '正式'
    return '候选'


def zones_frame(zones, candidates=[]):
    rows=[]
    for z in zones+candidates:
        rows.append({
            'Zone ID':z['zone_id'], '类型':'压力' if z['origin_type']=='R' else '支撑',
            '下沿':z['low'],'上沿':z['high'],'中心':z['center'],'触碰次数':z['touches'],
            '强度':strength_label(z['touches']),'首次触碰':z['first_touch_date'],'确认日期':z['confirmed_date'],
            '最近触碰':z['last_touch_date'],'当前状态':z.get('status','候选'),'最大反应ATR':z['max_reaction_atr']
        })
    return pd.DataFrame(rows)


def plot_chart(df, zones, ticker, bars=180):
    d=df.tail(bars)
    fig=go.Figure(data=[go.Candlestick(x=d.index,open=d['Open'],high=d['High'],low=d['Low'],close=d['Close'],name=ticker)])
    x0=d.index[0]; x1=d.index[-1]
    for z in zones:
        if z['confirmed_date'] > x1: continue
        start=max(pd.Timestamp(z['confirmed_date']), x0)
        fill='rgba(255,0,0,0.10)' if z['origin_type']=='R' else 'rgba(0,160,0,0.10)'
        line='rgba(220,0,0,0.55)' if z['origin_type']=='R' else 'rgba(0,130,0,0.55)'
        fig.add_shape(type='rect', x0=start, x1=x1, y0=z['low'], y1=z['high'], fillcolor=fill, line=dict(color=line,width=1), layer='below')
        fig.add_annotation(x=x1,y=z['center'],text=f"{z['zone_id']} | {z['touches']}次",showarrow=False,xanchor='right')
    fig.update_layout(height=700,xaxis_rangeslider_visible=False,margin=dict(l=20,r=20,t=50,b=20),title=f'{ticker} 日K：冻结式永久 Zone 模拟')
    return fig


st.title('🧪 CMS Permanent Zone Research v1')
st.caption('目标：不用图像识别，用日K模拟“反复触碰的支撑/压力区”。Zone 在第3次有效触碰时确认并冻结边界；以后只更新触碰次数和状态，不移动价格区间。研究版不会修改 A/B/C，也不会调用 Business Quant 或 Yahoo。')

if 'zone_snapshot' not in st.session_state:
    st.session_state.zone_snapshot=None

c1,c2=st.columns([1,2])
with c1:
    if st.button('📥 读取并锁定 Supabase 122只日K（一次）', type='primary', use_container_width=True):
        with st.spinner('读取 Supabase...'):
            try:
                snap=load_snapshot(UNIVERSE)
                st.session_state.zone_snapshot=snap
                st.success(f'已锁定 {len(snap)}/{len(UNIVERSE)} 只股票。后续本次会话不再读取 Supabase。')
            except Exception as e:
                st.error(str(e))
with c2:
    snap=st.session_state.zone_snapshot
    if snap:
        dates=[x.index.max() for x in snap.values() if x is not None and not x.empty]
        st.success(f'当前内存快照：{len(snap)}只；最新日期 {max(dates).date() if dates else "N/A"}')
    else:
        st.info('尚未读取快照。')

st.divider()
snap=st.session_state.zone_snapshot
if snap:
    a,b,c,d=st.columns(4)
    with a: ticker=st.selectbox('股票', sorted(snap.keys()), index=sorted(snap.keys()).index('CEG') if 'CEG' in snap else 0)
    with b: cluster_atr=st.selectbox('同一区域容差', [0.35,0.50,0.65,0.80], index=1, format_func=lambda x:f'{x:.2f} ATR')
    with c: reaction_atr=st.selectbox('有效反应门槛', [0.5,0.8,1.0,1.2], index=1, format_func=lambda x:f'{x:.1f} ATR')
    with d: min_gap=st.selectbox('两次触碰最小间隔', [3,5,7,10], index=1, format_func=lambda x:f'{x} 个交易日')

    # reaction_atr is applied via temporary local detector wrapper by recreating build internals
    # Keep formal research default at 0.8 ATR. If changed, use a local copy of detector behavior.
    original_detect=detect_pivots
    def detect_local(df, left=3, right=3, reaction_atr_unused=0.8, reaction_bars=5):
        return original_detect(df,left,right,reaction_atr,reaction_bars)
    globals()['detect_pivots']=detect_local
    zones,cands,pivots=build_frozen_zones(ticker,snap[ticker],cluster_atr=cluster_atr,min_gap=min_gap,confirm_touches=3)
    globals()['detect_pivots']=original_detect

    m1,m2,m3,m4=st.columns(4)
    m1.metric('正式 Zone',len(zones))
    m2.metric('压力 Zone',sum(z['origin_type']=='R' for z in zones))
    m3.metric('支撑 Zone',sum(z['origin_type']=='S' for z in zones))
    m4.metric('2次候选 Zone',len(cands))

    zdf=zones_frame(zones,cands)
    st.subheader('永久 Zone 清单')
    if not zdf.empty:
        st.dataframe(zdf.style.format({'下沿':'${:.2f}','上沿':'${:.2f}','中心':'${:.2f}','最大反应ATR':'{:.2f}'}),hide_index=True,use_container_width=True)
    else:
        st.warning('当前参数下没有形成 Zone。')

    st.subheader('图形核对：程序 Zone vs 人眼看K线')
    st.plotly_chart(plot_chart(snap[ticker],zones,ticker),use_container_width=True)

    with st.expander('查看所有有效 Swing High / Swing Low'):
        pdf=pd.DataFrame(pivots)
        if not pdf.empty:
            pdf['类型']=pdf['type'].map({'R':'Swing High / 压力触碰','S':'Swing Low / 支撑触碰'})
            st.dataframe(pdf[['date','类型','price','atr','reaction']].style.format({'price':'${:.2f}','atr':'{:.2f}','reaction':'{:.2f} ATR'}),hide_index=True,use_container_width=True)

    st.info('研究原则：2次=候选；第3次有效触碰=确认并冻结 Zone；4次=强；5次以上=非常强。确认后新增触碰只增加次数，不修改 Zone 上下沿。当前版本先用于“看图核对是否像人眼”，不会进入 A 买/不买，也不会进入 B BUY。')
else:
    st.warning('先点击上方按钮读取并锁定一次 Supabase 快照。')
