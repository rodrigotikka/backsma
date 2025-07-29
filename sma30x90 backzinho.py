# Streamlit app — SMA‑based buy/sell back‑tester
# --------------------------------------------------
# Requisitos:
#   pip install streamlit pandas openpyxl xlsxwriter
# Execução:
#   streamlit run sma_strategy_app.py
# --------------------------------------------------
import io
from datetime import datetime
from typing import Tuple

import pandas as pd
import streamlit as st

# --------------------------------------------------
# Funções utilitárias
# --------------------------------------------------

def _detect_tickers(df: pd.DataFrame) -> Tuple[str, pd.DataFrame]:
    """Retorna modo de organização (coluna ou planilhas) e lista de tickers."""
    if "Ticker" in df.columns:  # único Sheet com coluna "Ticker"
        tickers = sorted(df["Ticker"].dropna().unique())
        return "column", tickers
    else:
        # Sem coluna; cada sheet deve ter um ticker — tratamos fora
        return "sheet", []


def calculate_strategy(df: pd.DataFrame, buy_usd: float, sell_usd: float,
                        threshold_pct: float = 20.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Calcula SMAs, executa compras/vendas e devolve (dados, trades)."""
    df = df.copy().sort_values("Date")

    # Garantir dtype correto
    df["Date"] = pd.to_datetime(df["Date"])
    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"

    if price_col not in df.columns:
        raise ValueError("Coluna de preço não encontrada. Esperado 'Adj Close' ou 'Close'.")

    df["SMA30"] = df[price_col].rolling(window=30).mean()
    df["SMA90"] = df[price_col].rolling(window=90).mean()

    trades = []
    shares_balance = 0.0
    cash_from_sales = 0.0
    total_spent = 0.0

    for _, row in df.iterrows():
        price = row[price_col]
        sma30, sma90 = row["SMA30"], row["SMA90"]
        if pd.isna(sma30) or pd.isna(sma90):
            continue

        # --- Vendas ---
        if sma30 > sma90 and price >= (1 + threshold_pct / 100) * sma30:
            shares_to_sell = sell_usd / price
            if shares_balance >= shares_to_sell:
                shares_balance -= shares_to_sell
                cash_from_sales += sell_usd
                trades.append({
                    "Date": row["Date"],
                    "Action": "Sell",
                    "USD_Value": sell_usd,
                    "Shares_Amount": shares_to_sell,
                    "Shares_Balance": shares_balance,
                    "Holding_Value_USD": shares_balance * price,
                    "USD_Spent_on_Buys": 0,
                    "USD_from_Sales": sell_usd,
                })

        # --- Compras ---
        elif sma30 < sma90:
            shares_to_buy = buy_usd / price
            shares_balance += shares_to_buy
            total_spent += buy_usd
            trades.append({
                "Date": row["Date"],
                "Action": "Buy",
                "USD_Value": buy_usd,
                "Shares_Amount": shares_to_buy,
                "Shares_Balance": shares_balance,
                "Holding_Value_USD": shares_balance * price,
                "USD_Spent_on_Buys": buy_usd,
                "USD_from_Sales": 0,
            })

    trades_df = pd.DataFrame(trades)

    # Resumo
    total_buys = trades_df[trades_df["Action"] == "Buy"].shape[0]
    total_sells = trades_df[trades_df["Action"] == "Sell"].shape[0]
    total_shares_bought = trades_df.loc[trades_df["Action"] == "Buy", "Shares_Amount"].sum()
    avg_price_paid = total_spent / total_shares_bought if total_shares_bought else None
    pnl = cash_from_sales - total_spent
    last_price = df[price_col].iloc[-1]
    holding_value = shares_balance * last_price
    market_pnl = cash_from_sales + holding_value - total_spent
    market_pnl_pct = market_pnl / total_spent * 100 if total_spent else 0

    summary = pd.DataFrame({
        "Métrica": [
            "Total de compras", "Total gasto em compras (USD)", "Total de ações compradas",
            "Preço médio pago (USD/ação)", "Total de vendas", "USD gerado em vendas",
            "Caixa – (compras - vendas)", "Valor de mercado do saldo de ações",
            "P&L total (USD)", "% de lucro/prejuízo total"
        ],
        "Valor": [
            total_buys,
            f"${total_spent:,.2f}",
            f"{total_shares_bought:.4f}",
            f"${avg_price_paid:,.2f}" if avg_price_paid else "N/A",
            total_sells,
            f"${cash_from_sales:,.2f}",
            f"${cash_from_sales - total_spent:,.2f}",
            f"${holding_value:,.2f}",
            f"${market_pnl:,.2f}",
            f"{market_pnl_pct:.2f}%",
        ]
    })

    return df, trades_df, summary

# --------------------------------------------------
# Interface Streamlit
# --------------------------------------------------

st.set_page_config(page_title="SMA Strategy Back‑Tester", layout="wide")
st.title("📈 SMA\_30 / SMA\_90 Strategy Back‑Tester")

uploaded_file = st.file_uploader("Faça upload de um arquivo Excel (até várias folhas ou com coluna 'Ticker')", type=["xlsx", "xls", "csv"])

if uploaded_file:
    # Carregamento flexível (Excel ou CSV)
    if uploaded_file.name.endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(uploaded_file)
        mode, tickers = _detect_tickers(pd.read_excel(xls, xls.sheet_names[0]))

        if mode == "sheet":
            tickers = xls.sheet_names
            choice = st.selectbox("Escolha o ticker (nome da sheet)", tickers)
            df_raw = pd.read_excel(xls, sheet_name=choice)
        else:
            choice = st.selectbox("Escolha o ticker", tickers)
            df_raw = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
            df_raw = df_raw[df_raw["Ticker"] == choice]
    else:  # CSV simples – precisa ter coluna Ticker ou apenas um ativo
        df_raw = pd.read_csv(uploaded_file)
        if "Ticker" in df_raw.columns:
            tickers = sorted(df_raw["Ticker"].unique())
            choice = st.selectbox("Escolha o ticker", tickers)
            df_raw = df_raw[df_raw["Ticker"] == choice]
        else:
            choice = st.text_input("Ticker (informativo)", value="N/A")

    # Parametrização
    st.subheader("Parâmetros da estratégia")
    col1, col2, col3 = st.columns(3)
    with col1:
        buy_usd = st.number_input("USD por COMPRA (SMA30 < SMA90)", min_value=1.0, value=10.0, step=1.0)
    with col2:
        sell_usd = st.number_input("USD por VENDA (condição > 20% acima da SMA30)", min_value=1.0, value=20.0, step=1.0)
    with col3:
        threshold_pct = st.number_input("% acima da SMA30 para vender", min_value=1.0, value=20.0, step=1.0)

    if st.button("Executar back‑test"):
        try:
            df_calc, trades, summary = calculate_strategy(df_raw, buy_usd, sell_usd, threshold_pct)

            st.success("✅ Estratégia executada com sucesso!")
            st.subheader("Resumo")
            st.dataframe(summary, use_container_width=True)

            st.subheader("Trades")
            st.dataframe(trades, use_container_width=True)

            # Download do Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                df_calc.to_excel(writer, sheet_name="Dados_SMAs", index=False)
                trades.to_excel(writer, sheet_name="Trades", index=False)
                summary.to_excel(writer, sheet_name="Resumo", index=False)
            st.download_button(
                label="📥 Baixar resultados (Excel)",
                data=buffer.getvalue(),
                file_name=f"backtest_{choice}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.error(f"Erro ao executar a estratégia: {e}")

else:
    st.info("⬆️ Faça upload de um arquivo Excel ou CSV para começar.")
