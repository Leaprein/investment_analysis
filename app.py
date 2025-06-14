import streamlit as st
import yfinance as yf
import pandas as pd
from pandas.tseries.offsets import BDay
import plotly.graph_objects as go

def obtener_book_value(ticker):
    dat = yf.Ticker(ticker)
    try:
        balance = dat.get_balance_sheet(freq='quarterly').T
    except Exception as e:
        st.error(f"No se pudo obtener el balance para {ticker}: {e}")
        return None

    cols_necesarias = ["TotalAssets", "TotalLiabilitiesNetMinorityInterest", "OrdinarySharesNumber"]
    if not all(col in balance.columns for col in cols_necesarias):
        st.warning(f"Balance sheet incompleto para {ticker}. Columnas encontradas: {list(balance.columns)}")
        return None
    
    book_value_total = balance["TotalAssets"] - balance["TotalLiabilitiesNetMinorityInterest"]
    shares_outstanding = balance["OrdinarySharesNumber"]
    balance["BookValue"] = book_value_total / shares_outstanding
    
    balance = balance.reset_index().rename(columns={"index": "Date"})
    balance["Quarter"] = balance["Date"].dt.to_period("Q").astype(str)

    df_result = balance[["Date", "Quarter", "BookValue", "OrdinarySharesNumber"]]
    return df_result

def obtener_earnings(ticker):
    dat = yf.Ticker(ticker)
    try:
        earnings = dat.get_earnings_dates(limit=9).reset_index()
    except Exception as e:
        st.error(f"No se pudo obtener las fechas de earnings para {ticker}: {e}")
        return None
    
    if 'Earnings Date' not in earnings.columns:
        earnings.rename(columns={earnings.columns[0]: 'Earnings Date'}, inplace=True)

    def ajustar_fecha(row):
        fecha = row['Earnings Date']
        if isinstance(fecha, pd.Timestamp) and fecha.time() > pd.Timestamp('16:00:00').time():
            fecha = fecha + BDay(1)
        return fecha.date()

    earnings['Adjusted Date'] = earnings.apply(ajustar_fecha, axis=1)
    earnings['Adjusted Date'] = pd.to_datetime(earnings['Adjusted Date'])
    earnings['Date_minus_1bday'] = earnings['Adjusted Date'] - BDay(30)
    earnings['Quarter'] = earnings['Date_minus_1bday'].dt.to_period('Q').astype(str)
    
    return earnings[['Quarter', 'Adjusted Date']]

def descargar_precios(ticker, start_date):
    prices = yf.download(ticker, start=start_date, group_by='ticker', progress=False)
    if isinstance(prices.columns, pd.MultiIndex):
        prices.columns = [f"{i}_{j}" if j else i for i, j in prices.columns]
    prices = prices.reset_index()
    close_col = [col for col in prices.columns if col.endswith('_Close')]
    if not close_col:
        st.error("No se encontró columna de cierre en precios.")
        return None
    df = pd.DataFrame({
        'Ticker': ticker,
        'Date': prices['Date'],
        'Close': prices[close_col[0]]
    })
    return df

def calcular_price_to_book(df_prices, df_book_earnings):
    # Merge_asof para asignar BookValue según fecha más cercana atrás
    df_prices['Date'] = pd.to_datetime(df_prices['Date'])
    df_book_earnings['Adjusted Date'] = pd.to_datetime(df_book_earnings['Adjusted Date'])
    df_prices = df_prices.sort_values('Date')
    df_book_earnings = df_book_earnings.sort_values('Adjusted Date')
    
    merged = pd.merge_asof(df_prices, df_book_earnings[['Adjusted Date', 'BookValue']], 
                           left_on='Date', right_on='Adjusted Date', direction='backward')
    merged = merged.drop(columns=['Adjusted Date'])
    merged['PriceToBook'] = merged['Close'] / merged['BookValue']
    rolling_window = 365
    merged['PB_MA'] = merged['PriceToBook'].rolling(window=rolling_window, min_periods=1).mean()
    merged['PB_STD'] = merged['PriceToBook'].rolling(window=rolling_window, min_periods=1).std()
    merged['BB_Upper_1'] = merged['PB_MA'] + merged['PB_STD']
    merged['BB_Lower_1'] = merged['PB_MA'] - merged['PB_STD']
    merged['BB_Upper_2'] = merged['PB_MA'] + 2 * merged['PB_STD']
    merged['BB_Lower_2'] = merged['PB_MA'] - 2 * merged['PB_STD']
    
    return merged

def plot_price_to_book(df_pb, ticker):

        # Segundo gráfico
    ultimo_close = df_pb['Close'].iloc[-1]
    ultimo_ma = df_pb['PB_MA'].iloc[-1] * df_pb['BookValue'].iloc[-1]
    ultimo_up1 = df_pb['BB_Upper_1'].iloc[-1] * df_pb['BookValue'].iloc[-1]
    ultimo_up2 = df_pb['BB_Upper_2'].iloc[-1] * df_pb['BookValue'].iloc[-1]
    ultimo_low1 = df_pb['BB_Lower_1'].iloc[-1] * df_pb['BookValue'].iloc[-1]
    ultimo_low2 = df_pb['BB_Lower_2'].iloc[-1] * df_pb['BookValue'].iloc[-1]

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['Close'],
        mode='lines', name='Close',
        line=dict(color='blue')
    ))
    fig2.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['PB_MA'] * df_pb['BookValue'],
        mode='lines', name='Media Móvil (365d)',
        line=dict(color='black', dash='dash')
    ))
    fig2.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Upper_1'] * df_pb['BookValue'],
        mode='lines', name='Banda Superior 1σ',
        line=dict(color='red', width=1)
    ))
    fig2.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Upper_2'] * df_pb['BookValue'],
        mode='lines', name='Banda Superior 2σ',
        line=dict(color='red', width=3)
    ))
    fig2.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Lower_1'] * df_pb['BookValue'],
        mode='lines', name='Banda Inferior 1σ',
        line=dict(color='green', width=1)
    ))
    fig2.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Lower_2'] * df_pb['BookValue'],
        mode='lines', name='Banda Inferior 2σ',
        line=dict(color='green', width=3)
    ))

    texto_resumen = (
        f"<b>{ticker}</b><br>"
        f"Close: {ultimo_close:.2f}<br>"
        f"MA 365d: {ultimo_ma:.2f}<br>"
        f"Upper 1σ: {ultimo_up1:.2f}<br>"
        f"Upper 2σ: {ultimo_up2:.2f}<br>"
        f"Lower 1σ: {ultimo_low1:.2f}<br>"
        f"Lower 2σ: {ultimo_low2:.2f}"
    )
    fig2.add_annotation(
        xref="paper", yref="paper",
        x=0.02, y=1,
        showarrow=False,
        align="left",
        bordercolor="black",
        borderwidth=1,
        borderpad=8,
        bgcolor="white",
        text=texto_resumen
    )
    fig2.update_layout(
        title=f"Precio y Bandas Ajustadas - {ticker}",
        xaxis_title='Fecha',
        yaxis_title='Precio Absoluto',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified',
        template='plotly_white',
        height=600,
        margin=dict(r=150)
    )
    st.plotly_chart(fig2, use_container_width=True)

    # Primer gráfico
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['PriceToBook'],
        mode='lines', name='PriceToBook',
        line=dict(color='blue')
    ))
    fig1.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['PB_MA'],
        mode='lines', name='Media Móvil (365d)',
        line=dict(color='black', dash='dash')
    ))
    fig1.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Upper_1'],
        mode='lines', name='Banda Superior 1σ',
        line=dict(color='red', width=1)
    ))
    fig1.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Upper_2'],
        mode='lines', name='Banda Superior 2σ',
        line=dict(color='red', width=3)
    ))
    fig1.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Lower_1'],
        mode='lines', name='Banda Inferior 1σ',
        line=dict(color='green', width=1)
    ))
    fig1.add_trace(go.Scatter(
        x=df_pb['Date'], y=df_pb['BB_Lower_2'],
        mode='lines', name='Banda Inferior 2σ',
        line=dict(color='green', width=3)
    ))
    fig1.update_layout(
        title=f"Price-to-Book con Bandas de Bollinger - {ticker}",
        xaxis_title='Fecha',
        yaxis_title='Price-to-Book',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified',
        template='plotly_white',
        height=600,
        margin=dict(r=150)
    )
    st.plotly_chart(fig1, use_container_width=True)


# --- INTERFAZ STREAMLIT ---
st.title("Análisis Price-to-Book con Bandas de Bollinger")

tickers_list = ["GOOGL", "AMZN", "NVDA", "VIST", "AAPL", "NIO", "TSLA", "GLOB", "BBD", "MELI", "GPRK", "NU", "KO", "PBR", "VALE", "BRK-B", "MSFT",
               "PEP", "SATL", "AMD", "UNH", "PAGS", "BABA", "INTC", "NKE", "WMT", "AVGO", "PFE", "META", "COIN", "MSTR", "RIOT", "LLY",
               "DIS", "BIOX", "LAC", "CVX", "AAL", "ADBE", "PLTR", "V", "JMIA", "JNJ", "HMY", "SHOP", "PAAS", "XOM", "PG", "JD", "TSM", "MCD",
               "PYPL", "JMP", "QCOM", "MRNA", "RIO", "STLA", "BA", "DOCU", "BAC", "CRM", "MU", "MRK", "IBM", "ABNB", "MRVL", "VZ", "SBUX", "OXY",
               "MO", "F", "LAR", "NFLX", "ITUB", "CAT", "LRCX", "GE", "SPOT"]  # tu listado lo podés modificar

ticker = st.selectbox("Seleccionar CEDEAR", tickers_list)


with st.spinner(f"Cargando datos para {ticker}..."):
    df_book = obtener_book_value(ticker)
    if df_book is not None:
        df_earnings = obtener_earnings(ticker)
        if df_earnings is not None:
            # Merge de book_value con fechas earnings para tener BookValue en cada Adjusted Date
            df_book_earnings = pd.merge(df_book, df_earnings, on='Quarter', how='inner')

            fecha_inicio = df_book_earnings['Date'].min().strftime('%Y-%m-%d')
            df_prices = descargar_precios(ticker, start_date=fecha_inicio)

            if df_prices is not None:
                df_pb = calcular_price_to_book(df_prices, df_book_earnings)
                plot_price_to_book(df_pb, ticker)
            else:
                st.error("Error al descargar precios.")
        else:
            st.error("Error al obtener fechas de earnings.")
    else:
        st.error("Error al obtener book value o balance incompleto.")


