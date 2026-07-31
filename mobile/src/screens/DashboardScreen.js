import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { useFocusEffect } from '@react-navigation/native';
import API from '../api';
import { useTheme } from '../theme';

function HealthGauge({ score, size = 180, strokeWidth = 14, theme }) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.min(Math.max(score / 100, 0), 1);
  const strokeDashoffset = circumference * (1 - progress);

  const getColor = (s) => {
    if (s >= 80) return theme.success;
    if (s >= 50) return theme.warning;
    return theme.error;
  };

  return (
    <View style={{ alignItems: 'center', justifyContent: 'center' }}>
      <Svg width={size} height={size}>
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={theme.border}
          strokeWidth={strokeWidth}
          fill="none"
        />
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={getColor(score)}
          strokeWidth={strokeWidth}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          transform={`rotate(-90, ${size / 2}, ${size / 2})`}
        />
      </Svg>
      <View style={[styles.gaugeLabel, { position: 'absolute' }]}>
        <Text style={[styles.gaugeScore, { color: getColor(score) }]}>
          {Math.round(score)}
        </Text>
        <Text style={[styles.gaugeSub, { color: theme.textSecondary }]}>
          health
        </Text>
      </View>
    </View>
  );
}

function MetricCard({ label, value, unit, theme, accent }) {
  return (
    <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
      <Text style={[styles.cardLabel, { color: theme.textSecondary }]}>{label}</Text>
      <View style={styles.cardValueRow}>
        <Text style={[styles.cardValue, { color: accent || theme.text }]}>{value}</Text>
        {unit ? <Text style={[styles.cardUnit, { color: theme.textSecondary }]}>{unit}</Text> : null}
      </View>
    </View>
  );
}

export default function DashboardScreen() {
  const theme = useTheme();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);

      const status = await API.get('api/status');
      setData(status);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchData();
    }, [fetchData])
  );

  if (loading && !refreshing) {
    return (
      <View style={[styles.center, { backgroundColor: theme.background }]}>
        <ActivityIndicator size="large" color={theme.accent} />
      </View>
    );
  }

  const metrics = data?.metrics || {};
  const healthScore = metrics.health_score ?? data?.health_score ?? 0;
  const lastChecked = data?.last_checked || data?.timestamp || null;

  const metricCards = [
    { label: 'Orders', value: metrics.orders ?? metrics.total_orders ?? 0, accent: theme.accent },
    { label: 'Revenue', value: metrics.revenue ?? '$0', unit: '' },
    { label: 'Products', value: metrics.products ?? metrics.total_products ?? 0, accent: theme.success },
    { label: 'Health', value: healthScore, unit: '%', accent: healthScore >= 80 ? theme.success : healthScore >= 50 ? theme.warning : theme.error },
  ];

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: theme.background }]}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => fetchData(true)}
          tintColor={theme.accent}
        />
      }
    >
      <HealthGauge score={healthScore} theme={theme} />

      {lastChecked && (
        <Text style={[styles.timestamp, { color: theme.textSecondary }]}>
          Last checked: {new Date(lastChecked).toLocaleString()}
        </Text>
      )}

      <View style={styles.grid}>
        {metricCards.map((card, i) => (
          <MetricCard key={i} {...card} theme={theme} />
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { padding: 20, alignItems: 'center' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  gaugeLabel: { alignItems: 'center' },
  gaugeScore: { fontSize: 48, fontWeight: '700' },
  gaugeSub: { fontSize: 14, marginTop: -4 },
  timestamp: { fontSize: 12, marginTop: 12, marginBottom: 20 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, justifyContent: 'center' },
  card: {
    width: '46%',
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
  },
  cardLabel: { fontSize: 13, fontWeight: '500', marginBottom: 6 },
  cardValueRow: { flexDirection: 'row', alignItems: 'baseline', gap: 4 },
  cardValue: { fontSize: 26, fontWeight: '700' },
  cardUnit: { fontSize: 14, fontWeight: '500' },
});
