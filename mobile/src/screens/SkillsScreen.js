import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import API from '../api';
import { useTheme } from '../theme';

function SuccessRateBar({ rate, theme }) {
  const pct = Math.min(Math.max(rate || 0, 0), 100);
  const color = pct >= 90 ? theme.success : pct >= 70 ? theme.warning : theme.error;

  return (
    <View style={styles.barContainer}>
      <View style={[styles.barBg, { backgroundColor: theme.border }]}>
        <View
          style={[
            styles.barFill,
            { width: `${pct}%`, backgroundColor: color },
          ]}
        />
      </View>
      <Text style={[styles.barLabel, { color: theme.textSecondary }]}>
        {Math.round(pct)}%
      </Text>
    </View>
  );
}

function SkillCard({ skill, theme }) {
  const executions = skill.executions ?? skill.execution_count ?? skill.total ?? 0;
  const successes = skill.successes ?? skill.success_count ?? 0;
  const successRate = executions > 0 ? (successes / executions) * 100 : 0;
  const name = skill.name || skill.skill || skill.id || 'Unknown';
  const description = skill.description || '';

  return (
    <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
      <View style={styles.cardHeader}>
        <View style={styles.cardTitleRow}>
          <View style={[styles.dot, { backgroundColor: theme.accent }]} />
          <Text style={[styles.skillName, { color: theme.text }]}>{name}</Text>
        </View>
        {skill.version && (
          <Text style={[styles.version, { color: theme.textSecondary }]}>
            v{skill.version}
          </Text>
        )}
      </View>

      {description ? (
        <Text style={[styles.description, { color: theme.textSecondary }]} numberOfLines={2}>
          {description}
        </Text>
      ) : null}

      <View style={styles.statsRow}>
        <View style={styles.stat}>
          <Text style={[styles.statValue, { color: theme.text }]}>{executions}</Text>
          <Text style={[styles.statLabel, { color: theme.textSecondary }]}>executions</Text>
        </View>
        <View style={styles.stat}>
          <Text style={[styles.statValue, { color: theme.success }]}>{successes}</Text>
          <Text style={[styles.statLabel, { color: theme.textSecondary }]}>successes</Text>
        </View>
      </View>

      <View style={styles.rateSection}>
        <Text style={[styles.rateLabel, { color: theme.textSecondary }]}>Success Rate</Text>
        <SuccessRateBar rate={successRate} theme={theme} />
      </View>

      {skill.last_run && (
        <Text style={[styles.lastRun, { color: theme.textSecondary }]}>
          Last run: {new Date(skill.last_run).toLocaleString()}
        </Text>
      )}
    </View>
  );
}

export default function SkillsScreen() {
  const theme = useTheme();
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchSkills = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);

      const data = await API.get('api/status');
      const list = data?.skills || data?.agents || [];
      setSkills(Array.isArray(list) ? list : []);
    } catch {
      setSkills([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchSkills();
    }, [fetchSkills])
  );

  if (loading && !refreshing) {
    return (
      <View style={[styles.center, { backgroundColor: theme.background }]}>
        <ActivityIndicator size="large" color={theme.accent} />
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.background }]}>
      <FlatList
        data={skills}
        keyExtractor={(item, index) => String(item.name || item.skill || item.id || index)}
        renderItem={({ item }) => <SkillCard skill={item} theme={theme} />}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => fetchSkills(true)}
            tintColor={theme.accent}
          />
        }
        ListEmptyComponent={
          <Text style={[styles.empty, { color: theme.textSecondary }]}>
            No skills found
          </Text>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  list: { padding: 16 },
  card: {
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    marginBottom: 12,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  skillName: { fontSize: 16, fontWeight: '700' },
  version: { fontSize: 11, fontWeight: '500' },
  description: { fontSize: 13, marginBottom: 12, lineHeight: 18 },
  statsRow: { flexDirection: 'row', gap: 24, marginBottom: 12 },
  stat: { alignItems: 'center' },
  statValue: { fontSize: 20, fontWeight: '700' },
  statLabel: { fontSize: 11, marginTop: 2 },
  rateSection: { marginBottom: 8 },
  rateLabel: { fontSize: 12, fontWeight: '500', marginBottom: 4 },
  barContainer: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barBg: { flex: 1, height: 6, borderRadius: 3, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: 3 },
  barLabel: { fontSize: 12, fontWeight: '600', width: 36, textAlign: 'right' },
  lastRun: { fontSize: 11, marginTop: 4 },
  empty: { textAlign: 'center', marginTop: 40, fontSize: 15 },
});
