/**
 * E2E Test Configuration — defines test cases and expected behaviors.
 *
 * Each test case: { folder, zip, scripts, searches[] }
 *   searches: [{ table, field, expectedScripts, description }]
 */

const path = require('path');

const SAMPLE_BASE = path.resolve(__dirname, '../../samples');

module.exports = {
  // App endpoints — production frontend served by backend at port 8000
  appUrl: process.env.APP_URL || 'http://localhost:8000',
  apiUrl: process.env.API_URL || 'http://localhost:8000/api',

  // Browser settings
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  headless: true,

  // Timeouts (ms)
  timeouts: {
    pageLoad: 10000,
    upload: 8000,
    index: 15000,
    search: 5000,
    l2Open: 5000,
    layoutToggle: 3000,
    animation: 1000,
    export: 3000,
  },

  // Screenshot directory
  screenshotDir: path.resolve(__dirname, 'screenshots'),

  // Test cases — each becomes a full user session
  testCases: [
    {
      name: 'multi_workflow',
      folder: 'multi_workflow',
      zip: 'multi_workflow.zip',
      scripts: 5,
      searches: [
        {
          table: 'analytics_orders',
          field: 'amount',
          expectedScripts: 5,
          description: 'analytics_orders.amount — tracks through all 5 pipeline steps',
          // L2 scripts to open for detail verification
          l2Scripts: [
            { script: 'step1_load_orders.sql', expectedEdgesMin: 1, sqlLinesMin: 4 },
            { script: 'step3_join_orders_customers.sql', expectedEdgesMin: 2, sqlLinesMin: 4 },
          ],
        },
        {
          table: 'stg_orders',
          field: 'order_id',
          expectedScripts: 3,
          description: 'stg_orders.order_id — intermediate staging table',
        },
      ],
    },
    {
      name: 'multi_test',
      folder: 'multi_test',
      zip: 'multi_test.zip',
      scripts: 5,
      searches: [
        {
          table: 'gps_transactions',
          field: 'transaction_id',
          expectedScripts: 3,
          description: 'gps_transactions.transaction_id — GPS core transaction table',
          l2Scripts: [
            { script: '01_daily_volume.sql', expectedEdgesMin: 1, sqlLinesMin: 10 },
          ],
        },
      ],
    },
    {
      name: 'dialect_test',
      folder: 'dialect_test',
      zip: 'dialect_test.zip',
      scripts: 7,
      searches: [
        {
          table: 'orders',
          field: 'order_id',
          expectedScripts: 3,
          description: 'orders.order_id — multi-dialect (BigQuery/MaxCompute/Snowflake)',
          l2Scripts: [
            { script: 'bigquery_struct.sql', expectedEdgesMin: 1, sqlLinesMin: 3 },
          ],
        },
      ],
    },
    {
      name: 'tpcds_qualified',
      folder: 'tpcds_qualified',
      zip: 'tpcds_qualified.zip',
      scripts: 103,
      searches: [
        {
          table: 'store',
          field: 'cume_sales',
          expectedScripts: 10,
          description: 'store.cume_sales — TPC-DS qualified queries (103 scripts, 6252 lines, largest: 428 lines)',
          l2Scripts: [
            { script: 'tpcds_qualified/08.sql', expectedEdgesMin: 10, sqlLinesMin: 400 },
            { script: 'tpcds_qualified/10.sql', expectedEdgesMin: 20, sqlLinesMin: 60 },
          ],
        },
      ],
    },
    {
      name: 'financial',
      folder: 'financial',
      zip: 'financial.zip',
      scripts: 18,
      searches: [
        {
          table: 'gps_transactions',
          field: 'transaction_id',
          expectedScripts: 5,
          description: 'gps_transactions.transaction_id — financial analytics (18 scripts, large graph)',
          l2Scripts: [
            { script: 'fin_query10_fraud_detection.sql', expectedEdgesMin: 5, sqlLinesMin: 15 },
          ],
        },
      ],
    },
  ],

  // Features to test (each becomes a verification step)
  features: [
    'workspace_upload',
    'file_tree_display',
    'index_progress',
    'autocomplete_search',
    'l1_graph_render',
    'l1_node_interaction',
    'layout_toggle_snake_pipeline',
    'l2_open_double_click',
    'l2_graph_render',
    'l2_edge_click_sql_highlight',
    'l2_filter_toggle',
    'sql_panel_display',
    'sql_export',
    'panel_resize_drag',
    'workspace_delete',
    'l1_edge_click',
  ],
};
