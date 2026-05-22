import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# Configuración de la página de Streamlit
st.set_page_config(layout="wide", page_title="Análisis de Ineficiencias Logísticas")
st.title("📊 Monitor de Flujos, Ineficiencias y Cuellos de Botella")

archivo_cargado = st.file_uploader("Subí tu archivo de movimientos (Excel)", type=["xls", "xlsx"])

if archivo_cargado is not None:
    try:
        @st.cache_data
        def cargar_y_procesar(file):
            # Leer el Excel
            df = pd.read_excel(file)
            df.columns = df.columns.str.strip()
            df['Fecha'] = pd.to_datetime(df['Fecha'])
            
            # --- CORRECCIÓN DEL ERROR ---
            # 'errors=coerce' transforma cualquier texto inválido (como "-" o " ") en un valor vacío (NaN)
            df['Cantidad'] = pd.to_numeric(df['Cantidad'], errors='coerce')
            # .fillna(0) cambia esos vacíos (NaN) por un 0 numérico puro para que se pueda operar con < o >
            df['Cantidad'] = df['Cantidad'].fillna(0)
            
            # Aseguramos que los lotes sean texto limpio
            df['NroLote'] = df['NroLote'].astype(str).str.strip()
            
            return df

        df_base = cargar_y_procesar(archivo_cargado)
        
        # --- FILTROS ---
        st.sidebar.header("Filtros Operativos")
        
        # Filtro por Familia primero, para acotar
        familias = sorted(df_base['FAMILIA'].dropna().unique())
        familia_sel = st.sidebar.selectbox("1. Filtrar por Familia:", ["TODAS"] + familias)
        
        df_f = df_base if familia_sel == "TODAS" else df_base[df_base['FAMILIA'] == familia_sel]
        
        # Filtro por Artículo
        articulos = sorted(df_f['NomArticulo'].dropna().unique())
        articulo_sel = st.sidebar.selectbox("2. Selecciona el Producto:", articulos)
        
        df_filtrado = df_f[df_f['NomArticulo'] == articulo_sel].copy()

        # --- LÓGICA DE DERIVACIÓN DE ORIGEN Y DESTINO ---
        orig_dest = []
        for idx, row in df_filtrado.iterrows():
            tp = str(row['TP']).strip()
            dep = str(row['DEPOSITO']).strip()
            kg = row['Cantidad']
            
            orig, dest = None, None
            
            if tp in ['CPRA', 'FOB']:
                orig, dest = "Proveedor Ext.", dep
            elif tp == 'INI':
                orig, dest = "Stock Inicial (Virt.)", dep
            elif tp == 'CMV':
                orig, dest = dep, "Cliente (Venta)"
            elif tp == 'Baja_PRODUCC':
                orig, dest = dep, "Baja/Merma Proceso"
            elif tp == 'PRODUCC':
                if kg > 0:
                    orig, dest = "Linea Proceso (Virt.)", dep
                else:
                    orig, dest = dep, "Linea Proceso (Virt.)"
            elif tp == 'TRANSITO':
                if kg < 0:
                    orig, dest = dep, "Mercadería en Tránsito"
                else:
                    orig, dest = "Mercadería en Tránsito", dep
            elif tp in ['Ajuste', 'Ajuste_Evol']:
                if kg > 0:
                    orig, dest = "Ajustes de Inventario", dep
                else:
                    orig, dest = dep, "Ajustes de Inventario"
            
            # Si es FIN o no aplica, lo salteamos del flujo direccional
            if orig and dest:
                orig_dest.append({'Fecha': row['Fecha'], 'Lote': row['NroLote'], 'Origen': orig, 'Destino': dest, 'Kilos': abs(kg)})

        df_flujo = pd.DataFrame(orig_dest)

        if df_flujo.empty:
            st.warning("No se generaron flujos para el producto seleccionado con los códigos de movimiento actuales.")
        else:
            # --- DETECCIÓN DE INEFICIENCIAS (RULOS POR LOTE) ---
            st.subheader("⚠️ Alertas de Ineficiencias y Rulos Logísticos")
            
            # Buscamos lotes que se hayan movido más de una vez en movimientos internos
            # Excluimos Proveedores y Clientes para medir eficiencia interna propia
            df_internos = df_flujo[~df_flujo['Origen'].str.contains("Proveedor|Inicial") & ~df_flujo['Destino'].str.contains("Cliente|Baja")]
            
            # Contar movimientos por lote
            movimientos_por_lote = df_internos.groupby('Lote').size()
            lotes_con_rulos = movimientos_por_lote[movimientos_por_lote > 1]
            
            if not lotes_con_rulos.empty:
                col_al1, col_al2 = st.columns([2, 1])
                with col_al1:
                    st.error(f"Se detectaron {len(lotes_con_rulos)} Lotes con re-despacho interno excesivo (Falso Flete).")
                    # Detalle de esos lotes
                    df_alertas_lote = df_flujo[df_flujo['Lote'].isin(lotes_con_rulos.index)].sort_values(by=['Lote', 'Fecha'])
                    st.dataframe(df_alertas_lote[['Lote', 'Fecha', 'Origen', 'Destino', 'Kilos']], hide_index=True)
            else:
                st.success("✅ ¡Logística Eficiente! No se detectaron rulos ni movimientos redundantes de lotes en este producto.")

            st.markdown("---")

            # --- DIBUJO DEL MAPA DE FLUJO (SANKEY) ---
            nodos = list(pd.concat([df_flujo['Origen'], df_flujo['Destino']]).unique())
            nodo_a_id = {nodo: i for i, nodo in enumerate(nodos)}

            df_agrupado = df_flujo.groupby(['Origen', 'Destino'], as_index=False)['Kilos'].sum()

            fuente = df_agrupado['Origen'].map(nodo_a_id).tolist()
            destino = df_agrupado['Destino'].map(nodo_a_id).tolist()
            valores = df_agrupado['Kilos'].tolist()

            fig = go.Figure(data=[go.Sankey(
                node=dict(pad=18, thickness=25, line=dict(color="black", width=0.5), label=nodos, color="teal"),
                link=dict(source=fuente, target=destino, value=valores, color="rgba(102, 187, 106, 0.4)")
            )])
            
            fig.update_layout(title_text=f"Mapa de Distribución de Kilos: {articulo_sel}", height=550)

            # --- DESPLIEGUE VISUAL GRÁFICO Y TABLA ---
            c1, c2 = st.columns([3, 2])
            with c1:
                st.subheader("Mapa de Flujo Dinámico")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.subheader("Cuello de Botella (Acumulación)")
                # Agrupamos por destino para ver dónde se "frena" más mercadería
                st.write("Kilos totales recibidos por nodo destino en el período:")
                st.dataframe(df_agrupado.sort_values(by='Kilos', ascending=False), hide_index=True)

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")
else:
    st.info("💡 Esperando archivo de movimientos para mapear ineficiencias...")