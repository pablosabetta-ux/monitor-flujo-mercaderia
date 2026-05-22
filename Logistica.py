import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time

# Configuración de la página de Streamlit
st.set_page_config(layout="wide", page_title="Análisis de Ineficiencias Logísticas")
st.title("📊 Monitor de Flujos, Ineficiencias y Cuellos de Botella")
st.write("Visualización dinámica del movimiento de kilos y detección de rulos logísticos.")

archivo_cargado = st.file_uploader("Subí tu archivo de movimientos (Excel)", type=["xls", "xlsx"])

if archivo_cargado is not None:
    try:
        @st.cache_data
        def cargar_y_procesar(file):
           # 1. Leer el Excel
            df = pd.read_excel(file)
            df.columns = df.columns.str.strip()
            
            # 2. Forzar Fecha
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            
            # 3. Forzar Cantidad a Número Puro
            df['Cantidad'] = pd.to_numeric(df['Cantidad'], errors='coerce').fillna(0)
            
            # 4. BLINDAJE CRÍTICO: Forzar Lote a Texto Puro (así evitamos el error de comparación)
            # Primero cambiamos los vacíos por la palabra "SIN_LOTE"
            df['NroLote'] = df['NroLote'].fillna("SIN_LOTE")
            # Convertimos todo a string y limpiamos espacios
            df['NroLote'] = df['NroLote'].astype(str).str.strip()
            
            # 5. Asegurar que DEPOSITO y TP sean texto y no tengan nulos
            df['DEPOSITO'] = df['DEPOSITO'].fillna("DESCONOCIDO").astype(str).str.strip()
            df['TP'] = df['TP'].fillna("SIN_TP").astype(str).str.strip()

            return df

        df_base = cargar_y_procesar(archivo_cargado)
        
        # --- FILTROS ---
        st.sidebar.header("Filtros Operativos")
        
        # Filtro por Familia primero, para acotar
        familias = sorted(df_base['FAMILIA'].dropna().astype(str).unique())
        familia_sel = st.sidebar.selectbox("1. Filtrar por Familia:", ["TODAS"] + familias)
        
        df_f = df_base if familia_sel == "TODAS" else df_base[df_base['FAMILIA'].astype(str) == familia_sel]
        
        # Filtro por Artículo
        articulos = sorted(df_f['NomArticulo'].dropna().astype(str).unique())
        articulo_sel = st.sidebar.selectbox("2. Selecciona el Producto:", articulos)
        
        df_filtrado = df_f[df_f['NomArticulo'] == articulo_sel].copy()

        df_articulo = df_f[df_f['NomArticulo'] == articulo_sel].copy()
        
        # --- LÓGICA DE CONTROL DEL TIEMPO (REPRODUCTOR) ---
        st.sidebar.markdown("---")
        st.sidebar.header("⏱️ Control del Tiempo")

        # Obtenemos los meses únicos ordenados para este artículo
        meses_disponibles = sorted(df_articulo['MES'].unique())
        
        if len(meses_disponibles) > 0:
            # Inicializamos en el último índice (el final de la lista)
            ultimo_indice = len(meses_disponibles) - 1

            # Inicializamos una variable de estado en Streamlit para controlar el reproductor
            if "mes_index" not in st.session_state:
                st.session_state.mes_index = ultimo_indice

            # Protección extra: si cambiás de artículo y tiene menos meses que el anterior,
            # forzamos el índice a reajustarse al nuevo final para evitar desbordamientos.
            if st.session_state.mes_index >= len(meses_disponibles):
                st.session_state.mes_index = ultimo_indice

            # Botón de Play
            boton_play = st.sidebar.button("▶️ Reproducir Evolución")
            
            if boton_play:
            # Si le dan Play, forzamos a que empiece en el mes 0 y corra hacia el final
                for i, m in enumerate(meses_disponibles):
                    st.session_state.mes_index = i
                    mes_seleccionado = m
                    st.sidebar.text(f"Acumulando hasta: {m}")
                    time.sleep(1.2)
                    st.rerun()

            # El control deslizante ahora toma por defecto la posición actual guardada (que arranca al final)
            mes_seleccionado = st.sidebar.select_slider(
                "Hasta el mes:", 
                options=meses_disponibles,
                value=meses_disponibles[st.session_state.mes_index]
            )

            # Sincronizamos el estado si el usuario mueve el slider manualmente
            st.session_state.mes_index = meses_disponibles.index(mes_seleccionado)

            # Filtrado acumulativo en el tiempo
            df_filtrado = df_articulo[df_articulo['MES'] <= mes_seleccionado].copy()
        else:
            df_filtrado = df_articulo
            st.warning("No se encontraron datos en la columna MES para este artículo.")

        # --- CORRECCIÓN CRÍTICA: EXTRAER Y MOSTRAR STOCK INICIAL ESTÁTICO ---
        #st.subheader("📋 Foto de Inventario Inicial (No es movimiento)")
        
        # Filtramos los registros que sean INI en todo el historial cargado para este artículo
        #df_ini = df_articulo[df_articulo['TP'] == 'INI']
        
        #if not df_ini.empty:
            # Agrupamos por depósito para saber cuánto había en cada lugar al inicio de todo
        #    stock_inicial_por_dep = df_ini.groupby('DEPOSITO')['Cantidad'].sum()
            
            # Dibujamos tarjetas métricas lindas en columnas horizontales
        #   cols_metricas = st.columns(len(stock_inicial_por_dep))
        #    for idx, (deposito_nombre, kilos_iniciales) in enumerate(stock_inicial_por_dep.items()):
        #        with cols_metricas[idx]:
        #            st.metric(label=f"STK Inicial en {deposito_nombre}", value=f"{kilos_iniciales:,.0f} Kg")
        #else:
        #    st.info("No se registraron registros de Stock Inicial (INI) para este producto.")
        #st.markdown("---")

        # --- LÓGICA DE DERIVACIÓN DE ORIGEN Y DESTINO ---
        orig_dest = []
        for idx, row in df_filtrado.iterrows():
                        
            tp = str(row['TP']).strip()
            dep = str(row['DEPOSITO']).strip()

            # MODIFICACIÓN: Agregamos 'INI' a la lista de exclusión. Ya NO genera flechas de flujo.
            #if tp in ["SIN_TP", "FIN", "INI"] or dep == "DESCONOCIDO":
            if tp in ["SIN_TP", "TRANSITO"] or dep == "DESCONOCIDO":
                continue                
            
            # Forzamos que los kilos sean flotantes
            kg = float(row['Cantidad'])
            lote = row['NroLote']
            
            # Evitamos procesar lotes que no tengan tracking real si así lo deseamos
            if lote == "SIN_LOTE" or lote == "nan":
                continue

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
            
            df_internos = df_flujo[
                ~df_flujo['Origen'].str.contains("Proveedor|Inicial|Ajustes|Linea") & 
                ~df_flujo['Destino'].str.contains("Cliente|Baja|Ajustes|Linea")
            ]
            
            if not df_internos.empty:
                movimientos_por_lote = df_internos.groupby('Lote').size()
                lotes_con_rulos = movimientos_por_lote[movimientos_por_lote > 1]
                
                if not lotes_con_rulos.empty:
                    st.error(f"Se detectaron {len(lotes_con_rulos)} Lotes con re-despacho interno en este mes.")
                    df_alertas_lote = df_flujo[df_flujo['Lote'].isin(lotes_con_rulos.index)].copy()
                    df_alertas_lote['Fecha'] = df_alertas_lote['Fecha'].dt.strftime('%Y-%m-%d')
                    st.dataframe(df_alertas_lote[['Lote', 'Fecha', 'Origen', 'Destino', 'Kilos']].sort_values(by=['Lote', 'Fecha']), hide_index=True, use_container_width=True)
                else:
                    st.success("✅ ¡Logística Interna Eficiente! Sin rulos detectados en este período.")
            else:
                st.info("No se registran movimientos inter-depósitos en este mes.")
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
                st.subheader("Análisis de Concentración")
                st.write("Volumen total manejado por tramo:")
                df_tabla_ver = df_agrupado.copy()
                df_tabla_ver['Kilos'] = df_tabla_ver['Kilos'].map('{:,.2f}'.format)
                st.dataframe(df_tabla_ver.sort_values(by='Kilos', ascending=False), hide_index=True, use_container_width=True)
    
    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")
else:
    st.info("💡 Esperando archivo de movimientos para mapear ineficiencias...")