import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# Configuración de la página de Streamlit
st.set_page_config(layout="wide", page_title="Flujo de Mercadería")
st.title("📊 Monitor de Flujo de Mercadería")
st.write("Visualización dinámica del movimiento de kilos entre depósitos.")

# 1. COMPONENTE PARA IMPORTAR EL ARCHIVO XLS / XLSX
archivo_cargado = st.file_uploader("Seleccioná o arrastrá tu archivo de Excel", type=["xls", "xlsx"])

if archivo_cargado is not None:
    try:
        # Cargamos el archivo que el usuario subió
        # Usamos st.cache_data para que no tenga que leer el archivo en cada clic
        @st.cache_data
        def cargar_datos(file):
            df = pd.read_excel(file)
            
            # Limpieza estándar de nombres de columnas (quita espacios en blanco extras)
            df.columns = df.columns.str.strip()
            
            # Convertimos la columna Fecha a formato correcto
            if 'Fecha' in df.columns:
                df['Fecha'] = pd.to_datetime(df['Fecha'])
                
            return df

        df_base = cargar_datos(archivo_cargado)

        # Validamos que las columnas necesarias existan en el archivo importado
        columnas_requeridas = ['Fecha', 'Producto', 'Origen', 'Destino', 'Tipo_Movimiento', 'Kilos']
        columnas_faltantes = [col for col in columnas_requeridas if col not in df_base.columns]

        if columnas_faltantes:
            st.error(f"⚠️ Al archivo de Excel le faltan las siguientes columnas requeridas: {columnas_faltantes}")
        else:
            # 2. FILTROS EN LA BARRA LATERAL (Sidebar)
            st.sidebar.header("Filtros de Búsqueda")
            
            # Selector de Producto
            productos_disponibles = df_base['Producto'].unique()
            producto_seleccionado = st.sidebar.selectbox("Selecciona un Producto:", productos_disponibles)
            
            # Filtrado inicial por producto
            df_filtrado = df_base[df_base['Producto'] == producto_seleccionado]

            # Selector de Fechas dinámico basado en el producto elegido
            fecha_min = df_filtrado['Fecha'].min().date()
            fecha_max = df_filtrado['Fecha'].max().date()
            
            fechas = st.sidebar.date_input(
                "Rango de fechas:",
                value=[fecha_min, fecha_max],
                min_value=fecha_min,
                max_value=fecha_max
            )

            # Aplicar filtro de fechas si el usuario seleccionó el rango completo
            if len(fechas) == 2:
                df_filtrado = df_filtrado[
                    (df_filtrado['Fecha'].dt.date >= fechas[0]) & 
                    (df_filtrado['Fecha'].dt.date <= fechas[1])
                ]

            # 3. PREPARACIÓN DE DATOS PARA EL MAPA (SANKEY)
            # Consolidamos todos los lugares únicos (nodos)
            nodos = list(pd.concat([df_filtrado['Origen'], df_filtrado['Destino']]).unique())
            nodo_a_id = {nodo: i for i, nodo in enumerate(nodos)}

            # Agrupamos los kilos por Origen, Destino y Tipo para consolidar las líneas del mapa
            df_agrupado = df_filtrado.groupby(['Origen', 'Destino', 'Tipo_Movimiento'], as_index=False)['Kilos'].sum()

            # Mapeamos los nombres a IDs numéricos para Plotly
            fuente = df_agrupado['Origen'].map(nodo_a_id).tolist()
            destino = df_agrupado['Destino'].map(nodo_a_id).tolist()
            valores = df_agrupado['Kilos'].tolist()
            etiquetas_flujo = df_agrupado['Tipo_Movimiento'].tolist()

            # 4. CONSTRUCCIÓN DEL GRÁFICO DE FLUJO
            fig = go.Figure(data=[go.Sankey(
                node=dict(
                    pad=15,
                    thickness=20,
                    line=dict(color="black", width=0.5),
                    label=nodos,
                    color="darkblue"
                ),
                link=dict(
                    source=fuente,
                    target=destino,
                    value=valores,
                    label=etiquetas_flujo,
                    color="rgba(135, 206, 250, 0.5)" # Color celeste translúcido
                )
            )])

            fig.update_layout(title_text=f"Flujo de Kilos - {producto_seleccionado}", font_size=12, height=600)

            # 5. MOSTRAR EN PANTALLA (Gráfico y Tabla)
            col1, col2 = st.columns([3, 2])

            with col1:
                st.subheader("Mapa de Flujo (Sankey)")
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                st.subheader("Detalle de Movimientos")
                # Formateamos la columna Kilos para que sea más legible en la tabla
                df_tabla = df_filtrado[['Fecha', 'Origen', 'Destino', 'Tipo_Movimiento', 'Kilos']].copy()
                df_tabla['Fecha'] = df_tabla['Fecha'].dt.strftime('%Y-%m-%d')
                st.dataframe(df_tabla.sort_values(by='Fecha'), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Ocurrió un error al procesar el archivo: {e}")
else:
    st.info("💡 Por favor, subí un archivo Excel para comenzar el análisis.")