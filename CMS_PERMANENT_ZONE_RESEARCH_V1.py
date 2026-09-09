import streamlit as st
import pandas as pd
import numpy as np
import requests
import hashlib
import plotly.graph_objects as go

st.set_page_config(page_title='CMS Permanent Zone Research v2', layout='wide')

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
    return d.rename(columns={
        'adj_open':'Open','adj_high':'High','adj_low':'Low','adj_close':'Close','volume':'Volume'
    })[['Open','High','Low','Close','Volume']]


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
            h = dict(headers)
            h['Range'] = f'{start}-{start+999}'
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
    tr = pd.concat([
        (d['High']-d['Low']).abs(),
        (d['High']-pc).abs(),
        (d['Low']-pc).abs()
    ], axis=1).max(axis=1)
    d['ATR'] = tr.rolling(period, min_periods=5).mean()
    return d


def detect_pivots(df, left=3, right=3, reaction_atr=0.8, reaction_bars=5):
    d = add_atr(df)
    pivots=[]
    for i in range(left, len(d)-max(right, reaction_bars)):
        hi = d['High'].iloc[i]
        lo = d['Low'].iloc[i]
        atr = d['ATR'].iloc[i]
        if pd.isna(atr) or atr <= 0:
            continue
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


def _zone_id(ticker, confirmed_date, lo, hi):
    raw=f'{ticker}|{confirmed_date.date()}|{lo:.4f}|{hi:.4f}'
    return f'{ticker}-Z-' + hashlib.md5(raw.encode()).hexdigest()[:7].upper()


def _origin_role(types):
    r = sum(t == 'R' for t in types)
    s = sum(t == 'S' for t in types)
    if r > s:
        return '原压力'
    if s > r:
        return '原支撑'
    return '混合关键区'


def _strength_label(n):
    if n >= 5:
        return '非常强'
    if n == 4:
        return '强'
    if n >= 3:
        return '正式'
    return '候选'


def build_unified_frozen_zones(ticker, df, cluster_atr=0.5, min_gap=5, confirm_touches=3, reaction_atr=0.8):
    """
    v2核心：
    1) 支撑/压力不再分开建Zone；同一价格区域只保留一个永久Zone。
    2) 第3次独立有效触碰确认时冻结上下沿，之后边界不移动。
    3) 后续R/S触碰都记入同一个Zone，角色可随当前价格相对Zone的位置转换。
    """
    pivots = detect_pivots(df, reaction_atr=reaction_atr)
    zones=[]
    candidates=[]

    for p in pivots:
        matched=None
        for z in zones:
            if p['idx'] - z['last_touch_idx'] < min_gap:
                continue
            tol=max(cluster_atr*p['atr'], 0.0025*p['price'])
            if z['low']-tol <= p['price'] <= z['high']+tol:
                matched=z
                break

        if matched is not None:
            matched['touches'] += 1
            matched['touch_types'].append(p['type'])
            matched['touch_prices'].append(p['price'])
            matched['touch_dates'].append(p['date'])
            matched['last_touch_date'] = p['date']
            matched['last_touch_idx'] = p['idx']
            matched['max_reaction_atr'] = max(matched['max_reaction_atr'], p['reaction'])
            continue

        cm=None
        for c in candidates:
            if p['idx'] - c['last_idx'] < min_gap:
                continue
            center=float(np.median(c['prices']))
            tol=max(cluster_atr*p['atr'], 0.0025*p['price'])
            if abs(p['price']-center) <= tol:
                cm=c
                break

        if cm is None:
            candidates.append({
                'prices':[p['price']], 'atrs':[p['atr']], 'dates':[p['date']], 'idxs':[p['idx']],
                'types':[p['type']], 'reactions':[p['reaction']], 'last_idx':p['idx']
            })
        else:
            cm['prices'].append(p['price'])
            cm['atrs'].append(p['atr'])
            cm['dates'].append(p['date'])
            cm['idxs'].append(p['idx'])
            cm['types'].append(p['type'])
            cm['reactions'].append(p['reaction'])
            cm['last_idx']=p['idx']

            if len(cm['prices']) >= confirm_touches:
                # 只使用确认时已有的触碰冻结Zone，不随后续行情移动。
                center=float(np.median(cm['prices']))
                atr0=float(np.median(cm['atrs']))
                half=max(0.25*atr0, 0.003*center)
                lo=center-half
                hi=center+half
                z={
                    'ticker':ticker,
                    'low':lo,'high':hi,'center':center,
                    'confirmed_date':cm['dates'][-1],
                    'first_touch_date':cm['dates'][0],
                    'last_touch_date':cm['dates'][-1],
                    'touches':len(cm['prices']),
                    'touch_types':list(cm['types']),
                    'touch_prices':list(cm['prices']),
                    'touch_dates':list(cm['dates']),
                    'last_touch_idx':cm['idxs'][-1],
                    'max_reaction_atr':max(cm['reactions']),
                    'origin_role':_origin_role(cm['types'])
                }
                z['zone_id']=_zone_id(ticker, z['confirmed_date'], lo, hi)
                zones.append(z)
                candidates.remove(cm)

    cand_rows=[]
    for c in candidates:
        if len(c['prices']) >= 2:
            center=float(np.median(c['prices']))
            atr0=float(np.median(c['atrs']))
            half=max(0.25*atr0, 0.003*center)
            cand_rows.append({
                'ticker':ticker,'low':center-half,'high':center+half,'center':center,
                'confirmed_date':pd.NaT,'first_touch_date':c['dates'][0],'last_touch_date':c['dates'][-1],
                'touches':len(c['prices']),'zone_id':'候选','max_reaction_atr':max(c['reactions']),
                'origin_role':_origin_role(c['types']), 'touch_types':list(c['types'])
            })

    last_close=float(df['Close'].iloc[-1])
    last_date=pd.Timestamp(df.index[-1])
    for z in zones:
        if z['low'] <= last_close <= z['high']:
            current_role='正在测试关键区'
            distance=0.0
        elif last_close > z['high']:
            current_role='当前位于下方支撑背景'
            distance=(last_close-z['high'])/last_close
        else:
            current_role='当前位于上方压力背景'
            distance=(z['low']-last_close)/last_close
        z['current_role']=current_role
        z['distance_pct']=float(distance)
        z['days_since_touch']=int((last_date-z['last_touch_date']).days)
        z['strength']=_strength_label(z['touches'])

    return zones, cand_rows, pivots


def classify_distance(dist):
    if pd.isna(dist):
        return ''
    if dist <= 0.03:
        return '非常近'
    if dist <= 0.05:
        return '较近'
    if dist <= 0.10:
        return '中等距离'
    return '历史远端'


def current_zone_context(zones, price):
    inside=[z for z in zones if z['low'] <= price <= z['high']]
    above=[z for z in zones if z['low'] > price]
    below=[z for z in zones if z['high'] < price]
    nearest_above=min(above, key=lambda z:z['low']-price) if above else None
    nearest_below=min(below, key=lambda z:price-z['high']) if below else None
    current=min(inside, key=lambda z:abs(z['center']-price)) if inside else None
    return current, nearest_above, nearest_below


def zones_frame(zones, candidates=[]):
    rows=[]
    for z in zones:
        rows.append({
            'Zone ID':z['zone_id'],
            '原始属性':z['origin_role'],
            '下沿':z['low'],'上沿':z['high'],'中心':z['center'],
            '触碰次数':z['touches'],'强度':z['strength'],
            '压力触碰':sum(t=='R' for t in z['touch_types']),
            '支撑触碰':sum(t=='S' for t in z['touch_types']),
            '首次触碰':z['first_touch_date'],'确认日期':z['confirmed_date'],'最近触碰':z['last_touch_date'],
            '当前角色':z['current_role'],'距当前价':z['distance_pct'],
            '距离等级':classify_distance(z['distance_pct']),
            '距最近触碰天数':z['days_since_touch'],'最大反应ATR':z['max_reaction_atr']
        })
    for z in candidates:
        rows.append({
            'Zone ID':'候选','原始属性':z['origin_role'],'下沿':z['low'],'上沿':z['high'],'中心':z['center'],
            '触碰次数':z['touches'],'强度':'候选','压力触碰':sum(t=='R' for t in z['touch_types']),
            '支撑触碰':sum(t=='S' for t in z['touch_types']),'首次触碰':z['first_touch_date'],
            '确认日期':pd.NaT,'最近触碰':z['last_touch_date'],'当前角色':'候选','距当前价':np.nan,
            '距离等级':'','距最近触碰天数':np.nan,'最大反应ATR':z['max_reaction_atr']
        })
    return pd.DataFrame(rows)


def _zone_card(z, price, title):
    if z is None:
        st.metric(title, '无')
        return
    if z['low'] <= price <= z['high']:
        dist=0.0
    elif z['low'] > price:
        dist=(z['low']-price)/price
    else:
        dist=(price-z['high'])/price
    st.metric(title, f"${z['low']:.2f}–${z['high']:.2f}", f"距离 {dist:.1%} | {z['touches']}次")
    st.caption(f"{z['zone_id']} · {z['strength']} · {z['origin_role']} · 最近触碰 {pd.Timestamp(z['last_touch_date']).date()}")


def plot_chart(df, zones, ticker, price, bars=180, highlight_ids=None):
    d=df.tail(bars)
    fig=go.Figure(data=[go.Candlestick(
        x=d.index,open=d['Open'],high=d['High'],low=d['Low'],close=d['Close'],name=ticker
    )])
    x0=d.index[0]
    x1=d.index[-1]
    highlight_ids=set(highlight_ids or [])
    for z in zones:
        if z['confirmed_date'] > x1:
            continue
        start=max(pd.Timestamp(z['confirmed_date']), x0)
        if z['zone_id'] in highlight_ids:
            fill='rgba(255,165,0,0.18)'
            line='rgba(255,140,0,0.85)'
            width=2
        elif z['high'] < price:
            fill='rgba(0,160,0,0.08)'
            line='rgba(0,130,0,0.45)'
            width=1
        elif z['low'] > price:
            fill='rgba(255,0,0,0.08)'
            line='rgba(220,0,0,0.45)'
            width=1
        else:
            fill='rgba(255,165,0,0.12)'
            line='rgba(255,140,0,0.7)'
            width=2
        fig.add_shape(type='rect',x0=start,x1=x1,y0=z['low'],y1=z['high'],fillcolor=fill,line=dict(color=line,width=width),layer='below')
        fig.add_annotation(x=x1,y=z['center'],text=f"{z['zone_id']} | {z['touches']}次",showarrow=False,xanchor='right')
    fig.add_hline(y=price, line_dash='dot', annotation_text=f'当前 ${price:.2f}', annotation_position='top left')
    fig.update_layout(
        height=720,xaxis_rangeslider_visible=False,margin=dict(l=20,r=20,t=50,b=20),
        title=f'{ticker} 日K：统一永久 Zone（v2）'
    )
    return fig


st.title('🧪 CMS Permanent Zone Research v2')
st.caption(
    'v2目标：同一价格区域只保留一个永久 Zone；第3次独立有效触碰确认后冻结边界；'
    '支撑/压力允许角色转换；自动找当前最近上方/下方关键区。Zone 仅作市场地图，不参与 A 买/不买、B BUY 或 C SELL。'
)

if 'zone_snapshot_v2' not in st.session_state:
    st.session_state.zone_snapshot_v2=None

c1,c2=st.columns([1,2])
with c1:
    if st.button('📥 读取并锁定 Supabase 122只日K（一次）', type='primary', use_container_width=True):
        with st.spinner('读取 Supabase...'):
            try:
                snap=load_snapshot(UNIVERSE)
                st.session_state.zone_snapshot_v2=snap
                st.success(f'已锁定 {len(snap)}/{len(UNIVERSE)} 只股票。后续本次会话不再读取 Supabase。')
            except Exception as e:
                st.error(str(e))
with c2:
    snap=st.session_state.zone_snapshot_v2
    if snap:
        dates=[x.index.max() for x in snap.values() if x is not None and not x.empty]
        st.success(f'当前内存快照：{len(snap)}只；最新日期 {max(dates).date() if dates else "N/A"}')
    else:
        st.info('尚未读取快照。')

st.divider()
snap=st.session_state.zone_snapshot_v2
if snap:
    a,b,c,d=st.columns(4)
    tickers=sorted(snap.keys())
    with a:
        ticker=st.selectbox('股票',tickers,index=tickers.index('CEG') if 'CEG' in tickers else 0)
    with b:
        cluster_atr=st.selectbox('同一区域容差',[0.35,0.50,0.65,0.80],index=1,format_func=lambda x:f'{x:.2f} ATR')
    with c:
        reaction_atr=st.selectbox('有效反应门槛',[0.5,0.8,1.0,1.2],index=1,format_func=lambda x:f'{x:.1f} ATR')
    with d:
        min_gap=st.selectbox('两次触碰最小间隔',[3,5,7,10],index=1,format_func=lambda x:f'{x} 个交易日')

    df=snap[ticker]
    price=float(df['Close'].iloc[-1])
    zones,cands,pivots=build_unified_frozen_zones(
        ticker,df,cluster_atr=cluster_atr,min_gap=min_gap,confirm_touches=3,reaction_atr=reaction_atr
    )
    current,nearest_above,nearest_below=current_zone_context(zones,price)

    st.subheader('当前市场地图')
    m1,m2,m3,m4=st.columns(4)
    m1.metric('当前价格',f'${price:.2f}')
    with m2:
        _zone_card(nearest_below,price,'最近下方 Zone')
    with m3:
        _zone_card(nearest_above,price,'最近上方 Zone')
    with m4:
        if current:
            _zone_card(current,price,'当前正在测试')
        else:
            st.metric('当前正在测试','否')
            st.caption('当前价格不在任何正式 Zone 内。')

    st.caption('解释：最近上方/下方 Zone 只是位置背景，不是买卖信号；真正 BUY/SELL 仍由 A/B/C 原逻辑决定。')

    m1,m2,m3,m4=st.columns(4)
    m1.metric('正式 Zone',len(zones))
    m2.metric('非常强/强 Zone',sum(z['touches']>=4 for z in zones))
    m3.metric('发生过角色混合',sum(len(set(z['touch_types']))>1 for z in zones))
    m4.metric('2次候选 Zone',len(cands))

    st.subheader('永久 Zone 清单')
    zdf=zones_frame(zones,cands)
    if not zdf.empty:
        st.dataframe(
            zdf.style.format({
                '下沿':'${:.2f}','上沿':'${:.2f}','中心':'${:.2f}','距当前价':'{:.1%}',
                '最大反应ATR':'{:.2f}'
            },na_rep=''),
            hide_index=True,use_container_width=True
        )
    else:
        st.warning('当前参数下没有形成 Zone。')

    st.subheader('图形核对：统一 Zone vs 人眼看K线')
    highlight=[]
    for z in [current,nearest_above,nearest_below]:
        if z:
            highlight.append(z['zone_id'])
    st.plotly_chart(plot_chart(df,zones,ticker,price,highlight_ids=highlight),use_container_width=True)

    with st.expander('查看所有有效 Swing High / Swing Low'):
        pdf=pd.DataFrame(pivots)
        if not pdf.empty:
            pdf['类型']=pdf['type'].map({'R':'Swing High / 压力触碰','S':'Swing Low / 支撑触碰'})
            st.dataframe(
                pdf[['date','类型','price','atr','reaction']].style.format({
                    'price':'${:.2f}','atr':'{:.2f}','reaction':'{:.2f} ATR'
                }),hide_index=True,use_container_width=True
            )

    st.info(
        'v2研究原则：同一区域不再分别建立“支撑Zone”和“压力Zone”；第3次有效独立触碰确认后冻结边界；'
        '后续只更新触碰、角色和当前距离。Zone 永久保留，但“永久保留”不等于“永远是当前最重要Zone”。'
    )
else:
    st.warning('先点击上方按钮读取并锁定一次 Supabase 快照。')
